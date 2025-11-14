import json
import logging
import os
from datetime import datetime
from urllib.parse import unquote_plus

import boto3
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Initialize the logger, Get the log level from the environment variable
logger = logging.getLogger()
log_level = os.environ.get("LOG_LEVEL", "INFO")
logger.setLevel(log_level)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Configuration: Storage & Embeddings model
BUCKET_NAME = os.getenv("BUCKET_NAME")
PREFIX = os.getenv("PREFIX", "text")
VECTOR_BUCKET = os.getenv("VECTOR_BUCKET")
VECTOR_INDEX = os.getenv("VECTOR_INDEX")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 200))
EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
BATCH_WRITE_SIZE = 500  # max batch size for vector write API (as per AWS docs)

# Configuration: Clients
s3_client = boto3.client(service_name="s3", region_name=AWS_REGION)
s3_vector_client = boto3.client(service_name="s3vectors", region_name=AWS_REGION)
bedrock_client = boto3.client(service_name="bedrock-runtime", region_name=AWS_REGION)


def invoke_embeddings_model(chunks: list, model_id: str = EMBEDDING_MODEL_ID) -> list:
    """
    Invoke Bedrock model to generate embeddings.
    Default titan model v2.0

    :param chunks: LIST - document chunks
    :param model_id: STRING - model id
    :return: document chunks as embeddings list
    """
    logger.info(f"Invoking Bedrock embeddings model: {model_id}")

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
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
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
    logger.info(f"Split document into {len(chunks)} chunks")

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
                "source_url": f"s3://{BUCKET_NAME}/{PREFIX}/{document_name}",
                "source_text": chunk,
                "chunk_index": index,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "creation_timestamp": datetime.now().isoformat(),
            },
        }
        vectors.append(vector)

    # batch write to vector bucket/index
    for i in range(0, len(vectors), BATCH_WRITE_SIZE):
        partial_vector = vectors[i : i + BATCH_WRITE_SIZE]
        s3_vector_client.put_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=VECTOR_INDEX,
            vectors=partial_vector,
        )

    return vectors


def lambda_handler(event, context):
    """
    Triggered when a Text is uploaded to bucket/text/
    Generates embeddings and syncs them up on S3 Vector Index (Preview feature)
    """
    logger.info(f"Event :{event}")

    try:
        # Unpack event data
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = event["Records"][0]["s3"]["object"]["key"]

        # Decode URL-encoded key
        key = unquote_plus(key)
        logger.info(f"Processing: {bucket}/{key}")

        # Get text file locally
        text_obj = s3_client.get_object(Bucket=bucket, Key=key)
        text_document = text_obj["Body"].read()
        logger.debug(f"Document decoded: {text_document.decode("utf-8")}")

        # Split document into chunks and generate embeddings
        generate_embeddings(document=text_document.decode("utf-8"), document_name=key)

        logger.info(f"Successfully processed embeddings for: {bucket}/{key}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Embeddings created successfully", "output": key}
            ),
        }

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
