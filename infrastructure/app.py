#!/usr/bin/env python3
"""
AWS CDK App Entry Point for AI Trading System Infrastructure.

This app deploys the complete infrastructure for the multi-agent trading platform:
- DatabaseStack: DynamoDB tables with DAX, Timestream for market data
- NetworkStack: VPC with private subnets for Lambda functions
- SecurityStack: Secrets Manager, Cognito authentication
- ComputeStack: Lambda functions for agents and execution
- ApiStack: API Gateway WebSocket API for real-time updates
- ObservabilityStack: CloudWatch logging and audit trails
- MlStack: SageMaker endpoint for pattern recognition
"""
import aws_cdk as cdk

from stacks.database_stack import DatabaseStack
from stacks.network_stack import NetworkStack
from stacks.security_stack import SecurityStack
from stacks.compute_stack import ComputeStack
from stacks.api_stack import ApiStack
from stacks.observability_stack import ObservabilityStack
from stacks.ml_stack import MlStack


app = cdk.App()

# Environment configuration
env = cdk.Environment(
    account=app.node.try_get_context("account") or cdk.Aws.ACCOUNT_ID,
    region=app.node.try_get_context("region") or "us-east-1",
)

# Stack naming prefix
prefix = "ai-trading"

# Deploy stacks in dependency order
network_stack = NetworkStack(
    app,
    f"{prefix}-network",
    env=env,
    description="VPC and networking for AI Trading System",
)

database_stack = DatabaseStack(
    app,
    f"{prefix}-database",
    vpc=network_stack.vpc,
    env=env,
    description="DynamoDB tables, DAX cache, and Timestream for AI Trading System",
)

security_stack = SecurityStack(
    app,
    f"{prefix}-security",
    env=env,
    description="Secrets Manager and Cognito for AI Trading System",
)

observability_stack = ObservabilityStack(
    app,
    f"{prefix}-observability",
    env=env,
    description="CloudWatch logging and audit trails for AI Trading System",
)

ml_stack = MlStack(
    app,
    f"{prefix}-ml",
    vpc=network_stack.vpc,
    env=env,
    description="SageMaker endpoint for pattern recognition",
)

compute_stack = ComputeStack(
    app,
    f"{prefix}-compute",
    vpc=network_stack.vpc,
    database_stack=database_stack,
    security_stack=security_stack,
    observability_stack=observability_stack,
    ml_stack=ml_stack,
    env=env,
    description="Lambda functions for agents and execution",
)

api_stack = ApiStack(
    app,
    f"{prefix}-api",
    compute_stack=compute_stack,
    security_stack=security_stack,
    env=env,
    description="API Gateway WebSocket API for real-time dashboard updates",
)

# Add dependencies
database_stack.add_dependency(network_stack)
ml_stack.add_dependency(network_stack)
compute_stack.add_dependency(database_stack)
compute_stack.add_dependency(security_stack)
compute_stack.add_dependency(observability_stack)
compute_stack.add_dependency(ml_stack)
api_stack.add_dependency(compute_stack)
api_stack.add_dependency(security_stack)

app.synth()
