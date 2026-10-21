# AI Trading System - AWS Infrastructure

AWS CDK infrastructure for the AI-powered multi-agent trading platform.

## Architecture

The infrastructure is organized into the following stacks:

| Stack | Description | Requirements |
|-------|-------------|--------------|
| NetworkStack | VPC with private subnets, VPC endpoints | 11.5 |
| DatabaseStack | DynamoDB tables, DAX cache, Timestream | 9.1-9.5, 11.3 |
| SecurityStack | Secrets Manager, Cognito authentication | 11.1, 11.4 |
| ObservabilityStack | CloudWatch logging, audit trails | 10.5, 11.8 |
| MlStack | SageMaker endpoint for pattern recognition | 12.4 |
| ComputeStack | Lambda functions for agents and execution | 11.5, 11.6, 12.1, 12.2 |
| ApiStack | WebSocket API for real-time updates | 11.7, 12.5 |

## Prerequisites

- Python 3.11+
- AWS CDK CLI (`npm install -g aws-cdk`)
- AWS credentials configured

## Setup

```bash
cd infrastructure
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Deploy

```bash
# Bootstrap CDK (first time only)
cdk bootstrap

# Deploy all stacks
cdk deploy --all

# Deploy specific stack
cdk deploy ai-trading-database
```

## Key Resources

### DynamoDB Tables
- `ai-trading-signals` - News and Technical signals
- `ai-trading-decisions` - Trade decisions
- `ai-trading-records` - Executed trades

### Lambda Functions
- `ai-trading-news-agent` - News analysis with Bedrock
- `ai-trading-technical-agent` - Technical analysis (500ms latency)
- `ai-trading-strategy-agent` - Trade decision making
- `ai-trading-risk-manager` - Risk validation
- `ai-trading-order-executor` - MT5 order execution (reserved concurrency)
- `ai-trading-position-manager` - Position tracking

### Security
- MT5 credentials in Secrets Manager with 90-day rotation
- Cognito User Pool for dashboard authentication
- All Lambda functions in VPC with private subnets
- Least-privilege IAM roles

### Monitoring
- CloudWatch Log Groups for each component
- KMS-encrypted audit logs for trade decisions and executions
- Metric filters for error alerting
