
def chunking(text:str, chunk_size: int = 50, overlap: int = 20)->list[str]:
    text_splitted = text.split(" ")
    chunks = [
        " ".join(text_splitted[i:i+chunk_size]) 
        for i in range(0, len(text_splitted), chunk_size - overlap)
    ]
    return chunks