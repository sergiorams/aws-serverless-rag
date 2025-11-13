# RAG backed by S3 Vector Bucket (preview)

Build a serverless RAG system featuring the new S3 Vector Buckets for a **low-cost** solution.
Available on **US-EAST-1**

## Architecture diagram
![Alt Text](AWS_Serverless_Rag_Diagram.gif)

## Deploying Infrastructure

* Run `sam build`
* Run `sam deploy --guided`

### Create Bedrock Knowledge Base backed by S3 Vector, CLI command:
Since Vector buckets as Bedrock Knowledge Base are not yet supported by SAM we do this via the CLI.
Point Bedrock Knowledge Base to the S3 Vector bucket and index created above from the outputs:

**Outputs to be replaced:**

| key               | Description          | Value                  |
|-------------------|----------------------|------------------------|
| KnowledgeBaseRole | Bedrock role ARN     | Known after deployment |
| vectorBucketArn   | S3 Vector Bucket ARN | Known after deployment |
| indexArn          | S3 Vector Index ARN  | Known after deployment |

* Replace and Run
`
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
`

## How to use

Upload PDF documents to the S3 Data Bucket under the `/pdf` "directory" or directly to the `/text` directory.
after a few seconds, the system will index the documents and they will be ready to be queried.

## Endpoint

from outputs: **RagApiUrl**
Where top K is the most relevant documents to use as context.

``
curl -Method POST "<RagApiUrl>" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body '{
    "question": "Tell me something interesting about the cosmos",
    "user_id": "demo-user-1",
    "session_id": "session-1",
    "top_k": 3
  }'
``
