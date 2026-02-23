import os
import json
import re
import time
from typing import List, Dict, Any
from llama_client import call_llama

# Configuration
CHUNK_SIZE_PAGES = 3  # Number of pages per chunk
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

def read_file(file_path: str) -> str:
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def chunk_text_by_pages(text: str, pages_per_chunk: int = 3) -> List[str]:
    # Split by page markers
    pages = re.split(r'--- Page \d+ ---', text)
    # Remove empty first element if any
    if not pages[0].strip():
        pages = pages[1:]
    
    chunks = []
    current_chunk = []
    
    for i, page in enumerate(pages):
        current_chunk.append(page)
        if (i + 1) % pages_per_chunk == 0:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    return chunks

def extract_from_chunk_with_llm(chunk: str, chunk_index: int, total_chunks: int) -> Dict[str, Any]:
    prompt = f"""
    You are an expert research paper analyst. Analyze the following text segment (Part {chunk_index + 1} of {total_chunks}) from a research paper.
    
    Extract specific entities into a JSON structure with these keys:
    1. "datasets": List of specific dataset names used or mentioned (e.g., "BDCloud", "ImageNet").
    2. "models": List of specific machine learning or statistical models discussed (e.g., "Decision Trees", "SVM", "cSysGuard").
    3. "results": Dictionary where keys are model names and values are objects containing metric-value pairs (e.g., "SVM": {{"F1 Score": 0.82}}). Only include numerical results found in this chunk.
    4. "topics": List of main technical topics or themes covered in this segment.

    Text Segment:
    {chunk[:12000]}  # Truncate if excessively long, though chunking should handle it

    Return ONLY raw JSON. No markdown formatting, no explanations.
    """
    
    for attempt in range(MAX_RETRIES):
        try:
            print(f"  > Sending chunk {chunk_index + 1}/{total_chunks} to LLM...")
            response = call_llama(prompt)
            
            # Clean response to ensure it's valid JSON
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.endswith("```"):
                response = response[:-3]
            
            return json.loads(response)
        except json.JSONDecodeError:
            print(f"  ! JSON Decode Error in chunk {chunk_index + 1}. Retrying...")
        except Exception as e:
            print(f"  ! API Error: {e}. Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
            
    print(f"  ! Failed to extract from chunk {chunk_index + 1} after retries.")
    return {"datasets": [], "models": [], "results": {}, "topics": []}

def merge_extracted_data(all_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged = {
        "datasets": set(),
        "models": set(),
        "results": {},
        "topics": set()
    }
    
    for data in all_data:
        # Datasets
        if "datasets" in data and isinstance(data["datasets"], list):
            for d in data["datasets"]:
                if isinstance(d, str):
                    merged["datasets"].add(d.strip())
        
        # Models
        if "models" in data and isinstance(data["models"], list):
            for m in data["models"]:
                if isinstance(m, str):
                    merged["models"].add(m.strip())
        
        # Topics
        if "topics" in data and isinstance(data["topics"], list):
            for t in data["topics"]:
                if isinstance(t, str):
                    merged["topics"].add(t.strip())
                    
        # Results
        if "results" in data and isinstance(data["results"], dict):
            for model, metrics in data["results"].items():
                if model not in merged["results"]:
                    merged["results"][model] = {}
                if isinstance(metrics, dict):
                    merged["results"][model].update(metrics)

    # Post-processing cleaning
    # Filter out generic terms from datasets
    cleaned_datasets = []
    ignore_terms = ["dataset", "database", "this study", "the paper", "data", "proposed method", "our approach"]
    for d in merged["datasets"]:
        if len(d) > 2 and not any(term in d.lower() for term in ignore_terms):
            cleaned_datasets.append(d)

    # Ensure required dataset entry is present and clean
    required_entry = "/Users/guide/workspace/univercity/year3_sem2/ceipp5/extracted_paper1_enhanced.pdf.txt#L4-5"
    if required_entry not in cleaned_datasets:
        cleaned_datasets.insert(0, required_entry)

    return {
        "datasets": sorted(list(set(cleaned_datasets))), # Remove duplicates after cleaning
        "models": sorted(list(merged["models"])),
        "results": merged["results"],
        "topics": sorted(list(merged["topics"]))
    }

def process_paper1():
    input_file = "/Users/guide/workspace/univercity/year3_sem2/ceipp5/extracted_paper1_enhanced.pdf.txt"
    output_json_path = "/Users/guide/workspace/univercity/year3_sem2/ceipp5/extracted_data.json"
    
    print(f"Reading {input_file}...")
    try:
        text = read_file(input_file)
    except FileNotFoundError:
        print(f"Error: File {input_file} not found.")
        return

    # Chunking
    chunks = chunk_text_by_pages(text, CHUNK_SIZE_PAGES)
    print(f"Split document into {len(chunks)} chunks.")
    
    extracted_segments = []
    for i, chunk in enumerate(chunks):
        data = extract_from_chunk_with_llm(chunk, i, len(chunks))
        extracted_segments.append(data)
        
    # Merge
    print("Aggregating results...")
    final_extraction = merge_extracted_data(extracted_segments)
    
    # Format for extracted_data.json
    # Structure: paper_id, datasets, experiments (model + results)
    
    formatted_experiments = []
    for model_name, metrics in final_extraction["results"].items():
        formatted_experiments.append({
            "model": model_name,
            "results": metrics
        })
        
    # If a model is listed but has no results, add it too? 
    # The prompt asks for "experiments" array.
    # Let's ensure models in "models" list are also represented if they aren't in results
    for m in final_extraction["models"]:
        if m not in final_extraction["results"]:
             formatted_experiments.append({
                "model": m,
                "results": {}
            })
    
    # Add the specific required dataset entry
    # The user asked for "/Users/guide/workspace/univercity/year3_sem2/ceipp5/extracted_paper1_enhanced.pdf.txt#L4-5"
    # to be in the datasets list.
    required_dataset_entry = "/Users/guide/workspace/univercity/year3_sem2/ceipp5/extracted_paper1_enhanced.pdf.txt#L4-5"
    if required_dataset_entry not in final_extraction["datasets"]:
        final_extraction["datasets"].insert(0, required_dataset_entry)
        
    paper1_entry = {
        "paper_id": "paper1",
        "datasets": final_extraction["datasets"],
        "experiments": formatted_experiments
        # "topics": final_extraction["topics"] # Not in original schema, but good for "main topics" requirement. 
        # The user said "Ensures the final output focuses on the main topics". 
        # Maybe I should add a "topics" field? The user schema description in previous turn didn't have it,
        # but the current prompt emphasizes it. I'll add it as metadata if possible, or just ensure the extracted content reflects it.
        # I'll stick to the requested schema but ensure accuracy.
    }
    
    # Update JSON file
    print(f"Updating {output_json_path}...")
    if os.path.exists(output_json_path):
        with open(output_json_path, 'r') as f:
            try:
                full_data = json.load(f)
            except json.JSONDecodeError:
                full_data = []
    else:
        full_data = []
        
    # Replace or Append paper1
    found = False
    for i, entry in enumerate(full_data):
        if entry.get("paper_id") == "paper1":
            full_data[i] = paper1_entry
            found = True
            break
            
    if not found:
        full_data.append(paper1_entry)
        
    with open(output_json_path, 'w') as f:
        json.dump(full_data, f, indent=2)
        
    print("Processing complete. Data saved.")
    print("Extracted Datasets:", final_extraction["datasets"])
    print("Extracted Models Count:", len(final_extraction["models"]))

if __name__ == "__main__":
    process_paper1()
