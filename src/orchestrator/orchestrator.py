import json
import logging
import os

import boto3

# Initialize the logger, Get the log level from the environment variable
logger = logging.getLogger()
log_level = os.environ.get("LOG_LEVEL", "INFO")
logger.setLevel(log_level)

# CONFIGURATION: STORAGE & EMBEDDINGS MODEL
VECTOR_BUCKET = os.getenv("VECTOR_BUCKET", "staging-vector-bucket")
VECTOR_INDEX = os.getenv("VECTOR_INDEX", "vector-index")
EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-3-5-haiku-20241022-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
REBALANCE_THRESHOLD = 0.7

# CONFIGURATION: CLIENTS
s3_client = boto3.client(service_name="s3", region_name=AWS_REGION)
s3_vector_client = boto3.client(service_name="s3vectors", region_name=AWS_REGION)
bedrock_client = boto3.client(service_name="bedrock-runtime", region_name=AWS_REGION)

# PROMPT TEMPLATE
SYSTEM_PROMPT = (
    "You are an AI assistant specialized in answering questions about books and literature.\n"
    "You will be provided with relevant text extracts from books to help you answer the user questions.\n"
    "Guidelines:\n"
    "- Use only the provided context to answer questions.\n"
    "- If the context doesn't contain enough information, say so clearly.\n"
    "- Be conversational but informative.\n"
    "- Cite specific books or authors when relevant.\n"
    "- If no relevant context is provided, politely explain that you need more specific information.\n"
)


def retrieve_documents(
    query: str, top_k: int = 5, model_id: str = EMBEDDING_MODEL_ID
) -> list:
    """
    Retrieve relevant documents from the vector store based on a query.

    :param query: STRING - search query text
    :param top_k: INTEGER - number of top results to return (default: 5)
    :param model_id: STRING - embedding model ID for query embedding
    :return: list of relevant document chunks with metadata
    """
    logger.info(f"Retrieving documents for query: {query}")

    # Generate embedding for the query
    query_response = bedrock_client.invoke_model(
        modelId=model_id, body=json.dumps({"inputText": query})
    )

    # Extract embedding from response
    query_response_body = json.loads(query_response["body"].read())
    query_embedding = query_response_body["embedding"]

    # Search the vector store
    search_response = s3_vector_client.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        queryVector={"float32": query_embedding},
        topK=top_k,
        returnMetadata=True,
        returnDistance=True,
    )

    # Extract and format results
    results = []
    for result in search_response.get("vectors", []):
        if result.get("distance") < REBALANCE_THRESHOLD:
            document_info = {
                "key": result.get("key"),
                "distance": result.get("distance"),
                "metadata": result.get("metadata", {}),
                "source_text": result.get("metadata", {}).get("source_text", ""),
                "document_name": result.get("metadata", {}).get("document_name", ""),
                "chunk_index": result.get("metadata", {}).get("chunk_index", 0),
            }
            results.append(document_info)

    logger.info(f"Retrieved {len(results)} relevant documents")
    return results


def lambda_handler(event, context):
    """
    Lambda handler for API Gateway requests.

    Steps:
        1.- Retrieve relevant documents
        2.- Generate answer using an LLM
        3.- Prepare full response

    Expected input event: {"question": "Tell me something interesting about the cosmos?"}

    :return: {"answer": "...", "sources": [...], "metadata": {...}}
    """
    logger.info(f"Event :{event}")

    try:
        # Parse the request body
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]
        else:
            body = event

        # Extract the question
        question = body.get("question")
        if not question:
            return create_error_response(
                status_code=400, message="Missing 'question' in request body"
            )

        # Optional parameters
        top_k = body.get("top_k", 5)
        threshold = body.get("threshold", REBALANCE_THRESHOLD)

        logger.info(f"Processing question: {question}")

        # Retrieve relevant documents
        relevant_docs = retrieve_documents(question, top_k=top_k)

        if not relevant_docs:
            return create_success_response(
                answer=(
                    "I couldn't find any relevant information in the knowledge base to answer your question.\n"
                    "Please try rephrasing your question or asking about a different topic."
                ),
                sources=[],
                metadata={"documents_found": 0, "threshold_used": threshold},
            )

        # Generate answer using an LLM
        answer = generate_answer_with_llm(question, relevant_docs)

        # Prepare full response
        sources = prepare_sources(relevant_docs)
        metadata = {
            "documents_found": len(relevant_docs),
            "threshold_used": threshold,
            "llm_model": LLM_MODEL_ID,
            "embedding_model": EMBEDDING_MODEL_ID,
        }

        return create_success_response(answer, sources, metadata)

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return create_error_response(
            status_code=500, message=f"Internal server error: {str(e)}"
        )


def generate_answer_with_llm(question: str, relevant_docs: list) -> str:
    """
    Generate an answer using LLM (Default:  Claude 3.5 Haiku) with the retrieved context.

    :param question: User's question
    :param relevant_docs: List of relevant document chunks
    :return: Generated answer
    """
    logger.info(f"Generating answer with LLM for question: {question}")

    # Prepare context from relevant documents
    context_parts = []
    for i, doc in enumerate(relevant_docs, 1):
        context_parts.append(
            f"Source {i} - {doc['document_name']} (Chunk {doc['chunk_index']}):\n{doc['source_text']}"
        )
    context = "\n\n".join(context_parts)

    # Build prompt
    user_prompt = (
        "Context from books:\n"
        f"{context}"
        f"Question: {question}"
        "Please provide a helpful and informative answer based on the context provided above."
    )

    # Prepare the request for the LLM
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    try:
        response = bedrock_client.invoke_model(
            modelId=LLM_MODEL_ID, body=json.dumps(request_body)
        )

        # Parse the response
        response_body = json.loads(response["body"].read())
        answer = response_body["content"][0]["text"]

        logger.info("Successfully generated answer with Claude")
        return answer

    except Exception as e:
        logger.error(f"Error generating answer with Claude: {str(e)}")
        return f"I found relevant information but encountered an error generating the response: {str(e)}"


def prepare_sources(relevant_docs: list) -> list:
    """
    Prepare source information for the response.

    :param relevant_docs: List of relevant document chunks
    :return: List of source information
    """
    sources = []
    for doc in relevant_docs:
        source = {
            "document_name": doc["document_name"],
            "chunk_index": doc["chunk_index"],
            "similarity_score": round(
                1 - doc["distance"], 4
            ),  # Convert distance to similarity
            "excerpt": (
                doc["source_text"][:200] + "..."
                if len(doc["source_text"]) > 200
                else doc["source_text"]
            ),
        }
        sources.append(source)

    return sources


def create_success_response(answer: str, sources: list, metadata: dict) -> dict:
    """
    Create a successful API Gateway response.

    :param answer: Answer string
    :param sources: List of sources
    :param metadata: Additional metadata

    :return API Gateway response
    """
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps(
            {"answer": answer, "sources": sources, "metadata": metadata}
        ),
    }


def create_error_response(status_code: int, message: str) -> dict:
    """
    Create an error API Gateway response.

    :param status_code: HTTP status code
    :param message: Error message

    :return API Gateway response
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps({"error": message}),
    }
