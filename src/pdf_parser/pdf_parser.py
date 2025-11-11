import io
import json
from urllib.parse import unquote_plus

import boto3
from PyPDF2 import PdfReader

s3_client = boto3.client(service_name="s3")


def pdf_to_text(pdf_content: bytes) -> str:
    """
    Extracts text content from a PDF file supplied as a byte stream and extracts
    its textual content from all the pages.

    :param pdf_content: BYTES The binary content of the PDF file

    :return: The extracted text content from the PDF
    """
    # Extract text from PDF
    pdf_reader = PdfReader(io.BytesIO(pdf_content))
    page_texts = [page.extract_text() for page in pdf_reader.pages]
    return "\n".join(page_texts)


def lambda_handler(event, context):
    """
    Triggered when a PDF is uploaded to bucket/pdf/
    Extracts text and uploads to bucket/text/
    """
    print(f"Event :{event}")

    try:
        # Unpack event data
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = event["Records"][0]["s3"]["object"]["key"]

        # Decode URL-encoded key
        key = unquote_plus(key)
        print(f"Processing: {bucket}/{key}")

        # Get object locally
        pdf_obj = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_content = pdf_obj["Body"].read()

        # Extract text from PDF
        text = pdf_to_text(pdf_content=pdf_content)

        # Generate output key (replace pdf/ with text/ and .pdf with .txt)
        output_key = key.replace("pdf/", "text/").replace(".pdf", ".txt")

        # Upload text file to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=text.encode("utf-8"),
            ContentType="text/plain",
        )

        print(f"Successfully created: {bucket}/{output_key}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "PDF converted successfully", "output": output_key}
            ),
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
