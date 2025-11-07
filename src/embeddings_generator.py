import json
import os
from datetime import datetime

import boto3
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# CONFIGURATION AWS
REGION = os.getenv("AWS_REGION")

# CONFIGURATION S3
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
PREFIX = os.getenv("S3_PREFIX")
VECTOR_BUCKET = os.getenv("S3_VECTOR_BUCKET")
VECTOR_INDEX = os.getenv("S3_VECTOR_INDEX")
s3_client = boto3.client(service_name="s3")
s3_vector_client = boto3.client(service_name="s3vectors", region_name=REGION)

# CONFIGURATION EMBEDDINGS
EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID")
bedrock_client = boto3.client(service_name="bedrock-runtime", region_name=REGION)


def list_documents_from_s3(
    bucket: str = BUCKET_NAME, prefix: str = PREFIX, file_suffix: str = ".txt"
) -> list:
    """
    Get a list of text documents from S3 under the given prefix.

    :param bucket: STRING - S3 bucket name
    :param prefix: STRING - S3 prefix to filter documents
    :param file_suffix: STRING - file type suffix to filter documents

    :return: LIST - list of text document S3 paths
    """
    documents = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    files = [
        doc["Key"]
        for doc in documents.get("Contents", [])
        if doc["Key"].endswith(file_suffix)
    ]
    print(f"Listing S3 files and Found: {len(files)} files")

    return files


def read_s3_file_content(bucket: str = BUCKET_NAME, key: str = None) -> str:
    """
    Reads a file from an S3 bucket and retrieves its content as a dictionary.
    The file is expected to be in txt format.

    :param bucket: The name of the S3 bucket where the file is stored.
    :param key: The key (path) of the object in the S3 bucket to retrieve.

    :return: S3 text file as a string
    """
    # Get the object from S3, decode and return
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def invoke_embeddings_model(chunks: list, model_id: str = EMBEDDING_MODEL_ID) -> list:
    """
    Invoke Bedrock model to generate embeddings.
    Default titan model v2.0

    :param chunks: LIST - document chunks
    :param model_id: STRING - model id
    :return: document chunks as embeddings list
    """
    embeddings = []
    for chunk in chunks:
        response = bedrock_client.invoke_model(
            modelId=model_id, body=json.dumps({"inputText": chunk})
        )

        # Extract embedding from response
        response_body = json.loads(response["body"].read())
        embeddings.append(response_body["embedding"])

    return embeddings


def generate_embeddings(
    document: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    document_name: str = None,
):
    """
    Generates embeddings using the Titan model and stores them in a Chroma vector database.

    :param document: STRING document content as text string
    :param chunk_size: INTEGER size of each text chunk for processing (default: 1000)
    :param chunk_overlap: INTEGER number of characters to overlap between chunks (default: 200)
    :param document_name: STRING name of the document for metadata

    :return: Chroma db response
    """
    # split into chunks using recursive character text splitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    chunks = text_splitter.split_text(document)

    # get embeddings for each chunk
    embeddings = invoke_embeddings_model(chunks=chunks)

    # Enrich each chunk with additional metadata
    vectors = []
    for index, chunk in enumerate(chunks):
        vector = {
            "key": f"{document_name}_chunk_{index}",
            "data": {"float32": embeddings[index]},
            "metadata": {
                "document_name": document_name,
                "source_url": f"s3://{BUCKET_NAME}/{PREFIX}{document_name}.txt",
                "source_text": chunk,
                "chunk_index": index,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "creation_timestamp": datetime.now().isoformat(),
            },
        }
        vectors.append(vector)

    # write vector, 500-step increment (max batch size is 500 as per AWS docs)
    max_batch = 500
    for i in range(0, len(vectors), max_batch):
        partial_vector = vectors[i : i + max_batch]
        s3_vector_client.put_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=VECTOR_INDEX,
            vectors=partial_vector,
        )

    return vectors


def extract_document_name_from_s3_key(
    documents_key: str, prefix: str = PREFIX, suffix: str = ".txt"
) -> str:
    """
    Given some S3 object key, extract the book name.

    :param documents_key: STRING prefix + book name
    :param prefix: STRING prefix
    :param suffix: STRING suffix

    :return: only the name of the book, no suffix or prefix
    """
    return documents_key.replace(prefix, "").replace(suffix, "")


def main():
    """
    entry point, starts the embeddings-generation process.
    """
    # fetch documents paths from S3
    documents_keys = list_documents_from_s3(bucket=BUCKET_NAME, prefix=PREFIX)

    # load every document content as embeddings into S3 Vector Index
    for documents_key in documents_keys:
        print(f"Processing file: {documents_key}")
        document_name = extract_document_name_from_s3_key(documents_key=documents_key)
        document_content = read_s3_file_content(bucket=BUCKET_NAME, key=documents_key)
        generate_embeddings(document=document_content, document_name=document_name)


if __name__ == "__main__":
    main()
