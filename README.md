# RAG backed by S3 Vector Bucket (preview)

Build a serverless RAG system featuring the new S3 Vector Buckets for a **low-cost** solution.
Available on **US-EAST-1**

## Architecture diagram
![Alt Text](AWS_Serverless_Rag_Diagram.gif)

## Deploying Infrastructure

* Run `sam build`
* Run `sam deploy --guided`
  * Confirm changes before deploy [Y/n]: y
  * Allow SAM CLI IAM role creation [Y/n]: y
  * OrchestratorFunction has no authentication. Is this okay? [y/N]: y

### Create Bedrock Knowledge Base backed by S3 Vector, CLI command
Since Vector buckets as Bedrock Knowledge Base are not yet supported by SAM we do this via the CLI.
Point Bedrock Knowledge Base to the S3 Vector bucket and index created above from SAM outputs:

**Outputs to be replaced:**

| key               | Description          | Value                  |
|-------------------|----------------------|------------------------|
| KnowledgeBaseRole | Bedrock role ARN     | Known after deployment |
| vectorBucketArn   | S3 Vector Bucket ARN | Known after deployment |
| indexArn          | S3 Vector Index ARN  | Known after deployment |

* Replace and Run

````
aws bedrock-agent create-knowledge-base \
  --name "<knowledge base name>" \
  --description "Knowledge base backed by S3 vectors storage (preview add to SAM when available)" \
  --role-arn "<KnowledgeBaseRole output>" \
  --knowledge-base-configuration '{
    "type": "VECTOR",
    "vectorKnowledgeBaseConfiguration": {
      "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
      "embeddingModelConfiguration": {
        "bedrockEmbeddingModelConfiguration": {
          "dimensions": 1024,
          "embeddingDataType": "FLOAT32"
        }
      }
    }
  }' \
  --storage-configuration '{
    "type": "S3_VECTORS",
    "s3VectorsConfiguration": {
      "vectorBucketArn": "<SAM output: VectorBucketArn>",
      "indexArn": "<SAM output: IndexArn>"
    }
  }' \
  --region us-east-1
````


## How to use

1. Upload PDF documents to the S3 Data Bucket under the `/pdf` "directory" or directly to the `/text` directory.
2. Give it a minute to process the embeddings and sync to Bedrock Knowledge Base.
3. They is be ready to be queried via the API.


**Note:** This example system was feed multiple Carl Sagan's books for below response.

## Endpoint

from outputs: **RagApiUrl**
Where top K is the most relevant documents to use as context.

Sample request:

````
curl -Method POST "<RagApiUrl>" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body '{
    "question": "Tell me something interesting about the cosmos",
    "user_id": "demo-user-1",
    "session_id": "session-1",
    "top_k": 5
  }'
````

Sample response:



````
{
    "answer": "Based on the provided context from Carl Sagan's \"Cosmos,\" here are some fascinating insights about the Cosmos:\n\n1. Scale and Perspective\nThe Cosmos is incredibly vast and ancient, to the point where human affairs might seem insignificant. As Sagan poetically describes, we are \"Lost somewhere between immensity and eternity.\" Despite our seemingly small place in the universe, humans are \"young and curious and brave\" with great potential.\n\n2. Profound Interconnectedness\nSagan emphasizes that we are not separate from the Cosmos, but deeply connected to it. We are literally \"born from it,\" and our fate is intimately tied to the universe. He suggests that even the most basic human events trace back to cosmic origins.\n\n3. Emotional and Intellectual Wonder\nContemplating the Cosmos can be a profound experience. Sagan notes there's \"a tingling in the spine, a catch in the voice\" when we consider the universe - almost like a distant memory of falling from a height.\n\n4. Scientific Exploration\nThe Cosmos is full of incredible diversity - from \"quasars and quarks\" to \"snowflakes and fireflies,\" potentially including black holes, other universes, and even extraterrestrial civilizations. Science allows us to explore these mysteries, challenging us to understand the universe as it truly is, not as we wish it to be.\n\n5. Intellectual Humility\nSagan advocates for a scientific approach to understanding the Cosmos, which requires critical examination of all assumptions and a willingness to discard ideas inconsistent with facts. He warns against arrogance and the belief that we possess eternal truths.\n\nThe Cosmos, in Sagan's view, is a source of wonder, mystery, and endless potential for discovery.",
    "sources": [
        {
            "document_name": "text/Cosmos.txt",
            "chunk_index": 27,
            "distance_score": 0.48886269330978394,
            "extract": "deepest cosmological mysteries.\r\nToday we have discovered a powerful and elegant way to\r\nunderstand the universe, a method called science; it has revealed to\r\nus a universe so ancient and so vast that..."
        },
        {
            "document_name": "text/Cosmos.txt",
            "chunk_index": 46,
            "distance_score": 0.51705002784729,
            "extract": "to reclaim a little more land.\r\n—T. H. Huxley, 1887\r\nThe Cosmos is all that is or ever was or ever will be. Our\r\nfeeblest contemplations of the Cosmos stir us—there is a tingling in\r\nthe spine, a catc..."
        },
        {
            "document_name": "text/Cosmos.txt",
            "chunk_index": 972,
            "distance_score": 0.5437195897102356,
            "extract": "billion times—a Cosmos of quasars and quarks, snowflakes and\r\nfireflies, where there may be black holes and other universes and\r\nextraterrestrial civilizations whose radio messages are at this\r\nmoment..."
        },
        ...
````
