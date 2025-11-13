import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "rag-memory")

# DynamoDB client/resource
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


class ConversationMemory:
    """
    Handles conversation memory using DynamoDB
    """

    def __init__(self, table_name: str = DYNAMODB_TABLE):
        self.table_name = table_name
        self.table = dynamodb.Table(table_name)

    def store_message_pair(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Store a user-assistant message pair in DynamoDB

        :param user_id: STRING user id
        :param session_id: STRING session id
        :param user_message: STRING user query
        :param assistant_message: STRING LLM response
        :param metadata: DICTIONARY - extra information

        :return: boolean success or error
        """
        try:
            # composite key
            partition_key = f"{user_id}#{session_id}"
            sort_key = datetime.now().isoformat()

            # item schema
            item = {
                "conversation_id": partition_key,
                "timestamp": sort_key,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "metadata": metadata or {},
                "created_at": sort_key,
            }

            self.table.put_item(Item=item)
            logger.info(f"Stored message pair for {partition_key} at {sort_key}")
            return True

        except ClientError as e:
            logger.error(f"Failed to store message pair: {e}")
            return False

    def get_recent_conversation(
        self, user_id: str, session_id: str, limit: int = 5
    ) -> List[Dict]:
        """
        Get recent conversation history (last N message pairs)

        :param user_id: STRING User identifier
        :param session_id: STRING Session identifier
        :param limit: INT Number of recent message pairs to retrieve

        :return: List of message pairs, ordered from oldest to newest
        """
        try:
            partition_key = f"{user_id}#{session_id}"

            response = self.table.query(
                KeyConditionExpression="conversation_id = :pk",
                ExpressionAttributeValues={":pk": partition_key},
                ScanIndexForward=False,
                Limit=limit,
            )

            # Reverse to get chronological order (oldest first)
            messages = list(reversed(response.get("Items", [])))

            logger.info(f"Retrieved {len(messages)} message pairs for {partition_key}")
            return messages

        except ClientError as e:
            logger.error(f"Failed to retrieve conversation: {e}")
            return []

    def format_conversation_history(self, messages: List[Dict]) -> List[Dict]:
        """
        Format messages for LLM conversation
        Example:
            [{ role: "user", content: "..."}, { role: "assistant", content: "..." }]

        :param messages: List of message pairs from DynamoDB

        :return: List of formatted messages for Claude
        """
        formatted_messages = []

        for msg in messages:
            # Add user message
            formatted_messages.append(
                {"role": "user", "content": msg.get("user_message", "")}
            )

            # Add llm message
            formatted_messages.append(
                {"role": "assistant", "content": msg.get("assistant_message", "")}
            )

        return formatted_messages
