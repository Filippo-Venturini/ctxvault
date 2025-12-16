
from ctxvault.core.indexer import index_file
from ctxvault.core.querying import query

if __name__ == "__main__":
    file_path = "./data/test.md"
    query_txt = "What is the average latency in the version 3.2?"
    index_file(file_path=file_path)
    result = query(query_txt=query_txt)
    print(result)