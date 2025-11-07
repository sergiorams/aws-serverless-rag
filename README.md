# RAG using S3 Vector Bucket CLI

### first create an S3 Vector bucket, CLI command:
`aws s3vectors create-vector-bucket --vector-bucket-name knowledge-base-scientists-books --region us-east-1`

### Create vector index, CLI command:
(dimensions depend on the embedding model to be used)\
`aws s3vectors create-index \
  --region us-east-1 \
  --vector-bucket-name knowledge-base-scientists-books \
  --index-name "vector-index-books" \
  --data-type "float32" \
  --dimension 1024 \
  --distance-metric "cosine" \
  --metadata-configuration '{"nonFilterableMetadataKeys":["source_text", "source_url", "creation_timestamp"]}'`

### Create Bedrock Knowledge Base backed by S3 Vector, CLI command:
`aws bedrock-agent create-knowledge-base \
  --name "scientists-books-knowledge-base" \
  --description "Knowledge base backed by S3 vectors storage (preview)" \
  --role-arn "arn:aws:iam::074850731598:role/service-role/AmazonBedrockExecutionRoleForKnowledgeBase_RAGScientists" \
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
      "vectorBucketArn": "arn:aws:s3vectors:us-east-1:074850731598:bucket/knowledge-base-scientists-books",
      "indexArn": "arn:aws:s3vectors:us-east-1:074850731598:bucket/knowledge-base-scientists-books/index/vector-index-books"
    }
  }' \
  --region us-east-1
`
