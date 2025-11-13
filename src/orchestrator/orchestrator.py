import json
import logging
import os

import boto3
from memory import ConversationMemory

# Initialize the logger, Get the log level from the environment variable
logger = logging.getLogger()
log_level = os.environ.get("LOG_LEVEL", "INFO")
logger.setLevel(log_level)

# Configuration: Storage & Embeddings model
VECTOR_BUCKET = os.getenv("VECTOR_BUCKET", "staging-vector-bucket")
VECTOR_INDEX = os.getenv("VECTOR_INDEX", "vector-index")
EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-3-5-haiku-20241022-v1:0")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "staging-rag-memory")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
REBALANCE_THRESHOLD = 0.7

# Configuration: Clients
s3_client = boto3.client(service_name="s3", region_name=AWS_REGION)
s3_vector_client = boto3.client(service_name="s3vectors", region_name=AWS_REGION)
bedrock_client = boto3.client(service_name="bedrock-runtime", region_name=AWS_REGION)

# Initialize conversation memory
conversation_memory = ConversationMemory(table_name=DYNAMODB_TABLE)

# LLM System prompt
SYSTEM_PROMPT = (
    "You are an AI assistant specialized in answering questions about books and literature. "
    "You will be provided with:\n"
    "1. Previous conversation history (if any)\n"
    "2. Relevant text extracts from books to help answer the current question\n\n"
    "Guidelines:\n"
    "- Maintain conversational context from the chat history\n"
    "- Use the provided book extracts to answer questions accurately\n"
    "- If the context doesn't contain enough information, say so clearly\n"
    "- Be conversational but informative\n"
    "- Cite specific books or authors when relevant\n"
    "- If no relevant context is provided, politely explain that you need more specific information\n"
    "- Reference previous parts of the conversation when it makes sense to do so"
)


def lambda_handler(event, context):
    """
    Lambda handler for API Gateway requests with conversation memory.

    Expected input event: {
        "question": "Tell me something interesting about the cosmos?",
        "user_id": "user123",
        "session_id": "session456",
        "top_k": 5
    }

    :return: {"answer": "...", "sources": [...], "metadata": {...}}
    """
    logger.info(f"Event: {event}")

    try:
        # Parse the request body
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]
        else:
            body = event

        # Required parameters
        question = body.get("question")
        if not question:
            return create_error_response(
                status_code=400, message="Missing 'question' in request body"
            )
        user_id = body.get("user_id")
        if not user_id:
            return create_error_response(
                status_code=400, message="Missing 'user_id' in request body"
            )
        session_id = body.get("session_id")
        if not session_id:
            return create_error_response(
                status_code=400, message="Missing 'session_id' in request body"
            )

        # Optional parameters
        top_k = body.get("top_k", 5)
        threshold = body.get("threshold", REBALANCE_THRESHOLD)

        logger.info(
            f"Processing question: {question} for user: {user_id}, session: {session_id}"
        )

        # Get conversation history
        recent_messages = conversation_memory.get_recent_conversation(
            user_id=user_id, session_id=session_id, limit=5
        )

        # Retrieve relevant documents
        relevant_docs = retrieve_documents(query=question, top_k=top_k)

        if not relevant_docs:
            answer = (
                "I couldn't find any relevant information in the knowledge base to answer your question. "
                "Please try rephrasing your question or asking about a different topic."
            )
        else:
            # Generate answer using LLM with conversation history
            answer = generate_answer_with_llm(question, relevant_docs, recent_messages)

        # Store the new message pair
        sources = prepare_sources(relevant_docs)
        metadata = {
            "documents_found": len(relevant_docs),
            "threshold_used": threshold,
            "conversation_history_used": len(recent_messages),
            "llm_model": LLM_MODEL_ID,
            "embedding_model": EMBEDDING_MODEL_ID,
        }

        # Store conversation in DynamoDB
        conversation_stored = conversation_memory.store_message_pair(
            user_id=user_id,
            session_id=session_id,
            user_message=question,
            assistant_message=answer,
            metadata={"sources_count": len(sources), "model_used": LLM_MODEL_ID},
        )

        if not conversation_stored:
            logger.warning("Failed to store conversation in DynamoDB")

        return create_success_response(answer, sources, metadata)

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return create_error_response(
            status_code=500, message=f"Internal server error: {str(e)}"
        )


def retrieve_documents(
    query: str, top_k: int = 5, model_id: str = EMBEDDING_MODEL_ID
) -> list:
    """
    Retrieve relevant documents from the vector store based on a query.

    :param query: STRING A text query for which relevant documents need to be retrieved.
    :param top_k: INT Number of top documents to retrieve based on relevance (default is 5).
    :param model_id: STRING Model ID used to generate embeddings for the query, (default Titan model).

    :return: A list of relevant documents matching the query, including metadata and relevance details.
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

    # Extract and format relevant results
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


def generate_answer_with_llm(
    question: str, relevant_docs: list, conversation_history: list
) -> str:
    """
    Dynamically generate a prompt using the chat history and retrieved context, to then feed it to the LLM.

    :param question: STRING user question
    :param relevant_docs: LIST of documents from the RAG process
    :param conversation_history: LIST of message pairs from the conversation history

    :return: STRING assistant answer
    """
    logger.info(f"Generating answer with LLM for question: {question}")

    # Prepare context from relevant documents
    context_parts = []
    for i, doc in enumerate(relevant_docs, 1):
        context_parts.append(
            f"Source {i} - {doc['document_name']} (Chunk {doc['chunk_index']}):\n{doc['source_text']}"
        )
    context = "\n\n".join(context_parts)

    # Build messages array starting with conversation history
    messages = []

    # Add conversation history if it exists
    if conversation_history:
        history_messages = conversation_memory.format_conversation_history(
            conversation_history
        )
        messages.extend(history_messages)

        # Add a separator to clearly distinguish between history and current context
        messages.append(
            {"role": "user", "content": "--- Current Question with New Context ---"}
        )

    # Build the current question with context
    current_content = ""
    if context:
        current_content += f"Context from books:\n{context}\n\n"

    current_content += f"Question: {question}\n\n"
    current_content += "Please provide a helpful and informative answer based on the context provided above."

    if conversation_history:
        current_content += " Consider our previous conversation when relevant."

    messages.append({"role": "user", "content": current_content})

    # Prepare the request for the LLM
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }

    try:
        response = bedrock_client.invoke_model(
            modelId=LLM_MODEL_ID, body=json.dumps(request_body)
        )

        # Parse the response
        response_body = json.loads(response["body"].read())
        answer = response_body["content"][0]["text"]

        logger.info("Successfully generated answer with LLM")
        return answer

    except Exception as e:
        logger.error(f"Error generating answer with LLM: {str(e)}")
        return f"I found relevant information but encountered an error generating the response: {str(e)}"


def prepare_sources(relevant_docs: list) -> list:
    """
    Prepare source information for the response.

    :param relevant_docs: LIST of documents from the RAG process

    :return
    """
    sources = []
    for doc in relevant_docs:
        source = {
            "document_name": doc["document_name"],
            "chunk_index": doc["chunk_index"],
            "distance_score": doc["distance"],
            # sample extract if it's too long
            "extract": (
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

    :param answer: STRING assistant answer
    :param sources: STRING sources
    :param metadata: DICTIONARY metadata full source details

    :return: API Gateway response
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

    :param status_code: INT HTML status code
    :param message: STRING error message

    :return: API Gateway response
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


def main():
    """
    Main function for local testing of the complete RAG system with memory.
    """
    # Configure logger for local testing
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Test the Lambda handler locally with conversation memory
    test_event = {
        "body": json.dumps(
            {
                "question": "Do you remember my name?",
                "user_id": "test_user_123",
                "session_id": "test_session_456",
                "top_k": 3,
            }
        )
    }

    print("Testing Complete RAG System with Memory")
    print("=" * 50)

    response = lambda_handler(test_event, {})

    print(f"Status Code: {response['statusCode']}")
    print(f"Response Body: {json.dumps(json.loads(response['body']), indent=2)}")

    print("\n" + "=" * 50)
    print("✅ RAG system with memory testing completed")


if __name__ == "__main__":
    main()
