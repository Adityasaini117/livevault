"""Table creation script for LifeVault DynamoDB storage.

Creates the single-table DynamoDB table with PAY_PER_REQUEST billing.
Safe to re-run (idempotent).
"""

import os
from pathlib import Path
import sys

# Ensure server module is discoverable
server_dir = Path(__file__).resolve().parent
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

import boto3
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)
from dotenv import load_dotenv

# Load environment variables from .env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def create_lifevault_table(
    table_name: str | None = None,
    region_name: str | None = None,
    dynamodb_resource: None = None,
) -> None:
    """Create DynamoDB table with PAY_PER_REQUEST billing if it does not already exist."""
    tbl_name = table_name or os.getenv("DYNAMODB_TABLE", "lifevault-records")
    reg_name = region_name or os.getenv("AWS_REGION", "us-east-1")

    print(f"Checking DynamoDB table '{tbl_name}' in region '{reg_name}'...")

    try:
        dynamodb = dynamodb_resource or boto3.resource("dynamodb", region_name=reg_name)
        client = dynamodb.meta.client

        # Check if table already exists
        try:
            existing = client.describe_table(TableName=tbl_name)
            status = existing["Table"]["TableStatus"]
            print(f"Table '{tbl_name}' already exists with status: {status}.")
            return
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise

        # Create table with single-table schema
        print(f"Creating table '{tbl_name}' with PAY_PER_REQUEST billing...")
        table = dynamodb.create_table(
            TableName=tbl_name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print("Waiting for table to become ACTIVE...")
        table.wait_until_exists()
        print(f"Table '{tbl_name}' created successfully and is now ACTIVE.")

    except NoCredentialsError:
        print("ERROR: AWS credentials were not found. Please configure your AWS credentials via 'aws configure' or environment variables.")
        sys.exit(1)
    except EndpointConnectionError:
        print("ERROR: Could not connect to AWS. Please check your internet connection and region configuration.")
        sys.exit(1)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceInUseException":
            print(f"Table '{tbl_name}' already exists and is ready.")
            return
        if error_code in ("AccessDeniedException", "UnauthorizedOperation"):
            print("ERROR: Access denied. Please ensure your AWS IAM identity has 'dynamodb:CreateTable' and 'dynamodb:DescribeTable' permissions.")
            sys.exit(1)
        print(f"ERROR: AWS DynamoDB service error ({error_code}): {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error creating table: {e}")
        sys.exit(1)


if __name__ == "__main__":
    create_lifevault_table()
