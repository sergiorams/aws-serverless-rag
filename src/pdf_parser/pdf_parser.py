import json
import logging
import os
from urllib.parse import unquote_plus

import boto3
import pypdfium2 as pdfium

# Initialize the logger, Get the log level from the environment variable
logger = logging.getLogger()
log_level = os.environ.get("LOG_LEVEL", "INFO")
logger.setLevel(log_level)

# Configuration: Client
s3_client = boto3.client(service_name="s3")


def pdf_to_text(pdf_content: bytes) -> str:
    """
    Extracts text content from a PDF file supplied as a byte stream and extracts
    its textual content from all the pages.

    :param pdf_content: BYTES The binary content of the PDF file

    :return: The extracted text content from the PDF
    """
    try:
        pdf_doc = pdfium.PdfDocument(pdf_content)

        # Extract text from all pages
        text_pages = []
        for page in pdf_doc:
            text_page = page.get_textpage()
            text = text_page.get_text_range()
            if text.strip():  # Only add non-empty pages
                text_pages.append(text)
            text_page.close()
        pdf_doc.close()

        return "\n\n".join(text_pages)

    except Exception as e:
        logger.error(f"Error extracting text with pypdfium2: {str(e)}")
        raise


def lambda_handler(event, context):
    """
    Triggered when a PDF is uploaded to bucket/pdf/
    Extracts text and uploads to bucket/text/
    """
    logger.info(f"Event :{event}")

    try:
        # Unpack event data
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = event["Records"][0]["s3"]["object"]["key"]

        # Decode URL-encoded key
        key = unquote_plus(key)
        logger.info(f"Processing: {bucket}/{key}")

        # Get object locally
        pdf_obj = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_content = pdf_obj["Body"].read()
        logger.debug(f"Document document: {pdf_content}")

        # Extract text from PDF
        text = pdf_to_text(pdf_content=pdf_content)
        logger.info(f"Extracted {len(text)} characters")

        if not text.strip():
            text = "[No text could be extracted from this PDF]"
            logger.warning("No text extracted from PDF")

        # Generate output key (replace pdf/ with text/ and .pdf with .txt)
        output_key = key.replace("pdf/", "text/").replace(".pdf", ".txt")

        # Upload text file to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=text.encode("utf-8"),
            ContentType="text/plain",
        )

        logger.info(f"Successfully created: {bucket}/{output_key}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "PDF converted successfully", "output": output_key}
            ),
        }

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
