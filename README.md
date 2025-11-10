# RAG using S3 Vector Bucket CLI


## Deploy Infrastructure


### Create an S3 Bucket
This bucket is meant as the main landing zone for the documents in raw form, will store PDF and Text files:

`aws s3api create-bucket --bucket bucket-name --region us-east-1`

### Create an S3 Vector bucket:
S3 Vector bucket is where the vector representation of the data will be stored along with extra metadata:

`aws s3vectors create-vector-bucket --vector-bucket-name <vector-bucket-name> --region us-east-1`


### Create vector index:

Similar to a table in a relational database, the vector index is a collection of vectors and their metadata.
(dimensions depend on the embedding model to be used)

`aws s3vectors create-index \
  --region us-east-1 \
  --vector-bucket-name <vector-bucket-name> \
  --index-name <vector-index-name> \
  --data-type "float32" \
  --dimension 1024 \
  --distance-metric "cosine" \
  --metadata-configuration '{"nonFilterableMetadataKeys":["source_text", "source_url", "creation_timestamp"]}'`


### Create Bedrock Knowledge Base backed by S3 Vector, CLI command:

Point Bedrock Knowledge Base to the S3 Vector bucket and index created above:

`aws bedrock-agent create-knowledge-base \
  --name "scientists-books-knowledge-base" \
  --description "Knowledge base backed by S3 vectors storage (preview)" \
  --role-arn "arn:aws:iam::ACCOUNTID:role/service-role/<AmazonBedrockExecutionRoleForKnowledgeBase_RAG>" \
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
      "vectorBucketArn": "arn:aws:s3vectors:us-east-1:ACCOUNTID:bucket/<bucket-name>",
      "indexArn": "arn:aws:s3vectors:us-east-1:ACCOUNTID:bucket/<bucket-name>/index/<vector-index-name>"
    }
  }' \
  --region us-east-1
`
