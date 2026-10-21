"""
Compute Stack for AI Trading System.

Creates Lambda functions for:
- News Agent, Technical Agent, Strategy Agent
- Risk Manager, Order Executor, Position Manager
- WebSocket connection handlers

With:
- VPC configuration with private subnets (Requirement 11.5)
- Least-privilege IAM roles (Requirement 11.6)
- Reserved concurrency for Order Executor (Requirement 12.1, 12.2)

Requirements: 11.5, 11.6, 12.1, 12.2
"""
from aws_cdk import (
    Stack,
    Duration,
    Aws,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_logs as logs,
    CfnOutput,
)
from constructs import Construct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database_stack import DatabaseStack
    from .security_stack import SecurityStack
    from .observability_stack import ObservabilityStack
    from .ml_stack import MlStack


class ComputeStack(Stack):
    """Lambda functions for agents and execution in AI Trading System."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        database_stack: "DatabaseStack",
        security_stack: "SecurityStack",
        observability_stack: "ObservabilityStack",
        ml_stack: "MlStack",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = vpc
        self.database_stack = database_stack
        self.security_stack = security_stack
        self.observability_stack = observability_stack
        self.ml_stack = ml_stack

        # Lambda security group
        self.lambda_sg = ec2.SecurityGroup(
            self,
            "LambdaSecurityGroup",
            vpc=vpc,
            description="Security group for Lambda functions",
            allow_all_outbound=True,
        )

        # Common Lambda layer for shared code
        self.common_layer = lambda_.LayerVersion(
            self,
            "CommonLayer",
            layer_version_name="ai-trading-common",
            description="Common utilities for AI Trading System",
            code=lambda_.Code.from_asset("../src"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
        )

        # ============================================================
        # News Agent Lambda (Requirement 12.3)
        # ============================================================
        self.news_agent_role = self._create_news_agent_role()
        self.news_agent_function = lambda_.Function(
            self,
            "NewsAgentFunction",
            function_name="ai-trading-news-agent",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.news_scraper_handler.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(30),
            memory_size=512,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
            role=self.news_agent_role,
            environment={
                "SIGNALS_TABLE": database_stack.signals_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_group=observability_stack.news_agent_log_group,
        )

        # ============================================================
        # Technical Agent Lambda (Requirement 12.1)
        # ============================================================
        self.technical_agent_role = self._create_technical_agent_role()
        self.technical_agent_function = lambda_.Function(
            self,
            "TechnicalAgentFunction",
            function_name="ai-trading-technical-agent",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.technical_agent_handler.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.milliseconds(500),  # Requirement 12.1: 500ms latency
            memory_size=1024,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
            role=self.technical_agent_role,
            environment={
                "SIGNALS_TABLE": database_stack.signals_table.table_name,
                "TIMESTREAM_DATABASE": "ai-trading-market-data",
                "TIMESTREAM_TABLE": "ohlcv-candles",
                "SAGEMAKER_ENDPOINT": ml_stack.endpoint.endpoint_name or "ai-trading-pattern-recognition",
                "LOG_LEVEL": "INFO",
            },
            log_group=observability_stack.technical_agent_log_group,
        )

        # ============================================================
        # Strategy Agent Lambda
        # ============================================================
        self.strategy_agent_role = self._create_strategy_agent_role()
        self.strategy_agent_function = lambda_.Function(
            self,
            "StrategyAgentFunction",
            function_name="ai-trading-strategy-agent",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.strategy_agent_handler.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(10),
            memory_size=512,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
            role=self.strategy_agent_role,
            environment={
                "SIGNALS_TABLE": database_stack.signals_table.table_name,
                "DECISIONS_TABLE": database_stack.trade_decisions_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_group=observability_stack.strategy_agent_log_group,
        )

        # ============================================================
        # Risk Manager Lambda
        # ============================================================
        self.risk_manager_role = self._create_risk_manager_role()
        self.risk_manager_function = lambda_.Function(
            self,
            "RiskManagerFunction",
            function_name="ai-trading-risk-manager",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.risk_manager_handler.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(10),
            memory_size=256,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
            role=self.risk_manager_role,
            environment={
                "TRADES_TABLE": database_stack.trade_records_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_group=observability_stack.risk_manager_log_group,
        )

        # ============================================================
        # Order Executor Lambda (Requirement 12.2)
        # Reserved concurrency for critical trade execution
        # ============================================================
        self.order_executor_role = self._create_order_executor_role()
        self.order_executor_function = lambda_.Function(
            self,
            "OrderExecutorFunction",
            function_name="ai-trading-order-executor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.order_executor_handler.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(30),
            memory_size=512,
            reserved_concurrent_executions=10,  # Reserved concurrency
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
            role=self.order_executor_role,
            environment={
                "TRADES_TABLE": database_stack.trade_records_table.table_name,
                "MT5_SECRET_ARN": security_stack.mt5_credentials_secret.secret_arn,
                "AUDIT_LOG_GROUP": observability_stack.trade_executions_audit_log.log_group_name,
                "LOG_LEVEL": "INFO",
            },
            log_group=observability_stack.order_executor_log_group,
        )

        # ============================================================
        # Position Manager Lambda
        # ============================================================
        self.position_manager_role = self._create_position_manager_role()
        self.position_manager_function = lambda_.Function(
            self,
            "PositionManagerFunction",
            function_name="ai-trading-position-manager",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.position_manager_handler.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(10),
            memory_size=256,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
            role=self.position_manager_role,
            environment={
                "TRADES_TABLE": database_stack.trade_records_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            log_group=observability_stack.position_manager_log_group,
        )

        # ============================================================
        # WebSocket Handler Lambdas
        # ============================================================
        self.websocket_role = self._create_websocket_role()
        
        self.websocket_connect_function = lambda_.Function(
            self,
            "WebSocketConnectFunction",
            function_name="ai-trading-ws-connect",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.websocket_handler.connect",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(10),
            memory_size=128,
            role=self.websocket_role,
            environment={"LOG_LEVEL": "INFO"},
            log_group=observability_stack.websocket_log_group,
        )

        self.websocket_disconnect_function = lambda_.Function(
            self,
            "WebSocketDisconnectFunction",
            function_name="ai-trading-ws-disconnect",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.websocket_handler.disconnect",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(10),
            memory_size=128,
            role=self.websocket_role,
            environment={"LOG_LEVEL": "INFO"},
            log_group=observability_stack.websocket_log_group,
        )

        self.websocket_message_function = lambda_.Function(
            self,
            "WebSocketMessageFunction",
            function_name="ai-trading-ws-message",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handlers.websocket_handler.message",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(10),
            memory_size=128,
            role=self.websocket_role,
            environment={"LOG_LEVEL": "INFO"},
            log_group=observability_stack.websocket_log_group,
        )

        # Grant DynamoDB permissions
        database_stack.signals_table.grant_read_write_data(self.news_agent_function)
        database_stack.signals_table.grant_read_write_data(self.technical_agent_function)
        database_stack.signals_table.grant_read_data(self.strategy_agent_function)
        database_stack.trade_decisions_table.grant_read_write_data(self.strategy_agent_function)
        database_stack.trade_records_table.grant_read_write_data(self.order_executor_function)
        database_stack.trade_records_table.grant_read_write_data(self.position_manager_function)
        database_stack.trade_records_table.grant_read_data(self.risk_manager_function)

        # Grant Secrets Manager access to Order Executor
        security_stack.mt5_credentials_secret.grant_read(self.order_executor_function)

        # ============================================================
        # Outputs
        # ============================================================
        CfnOutput(self, "NewsAgentFunctionArn", value=self.news_agent_function.function_arn)
        CfnOutput(self, "TechnicalAgentFunctionArn", value=self.technical_agent_function.function_arn)
        CfnOutput(self, "StrategyAgentFunctionArn", value=self.strategy_agent_function.function_arn)
        CfnOutput(self, "OrderExecutorFunctionArn", value=self.order_executor_function.function_arn)

    def _create_news_agent_role(self) -> iam.Role:
        """Create least-privilege IAM role for News Agent."""
        role = iam.Role(
            self,
            "NewsAgentRole",
            role_name="ai-trading-news-agent-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ))
        role.add_managed_policy(self.security_stack.bedrock_policy)
        return role

    def _create_technical_agent_role(self) -> iam.Role:
        """Create least-privilege IAM role for Technical Agent."""
        role = iam.Role(
            self,
            "TechnicalAgentRole",
            role_name="ai-trading-technical-agent-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ))
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["timestream:WriteRecords", "timestream:DescribeEndpoints", "timestream:Select"],
            resources=["*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["sagemaker:InvokeEndpoint"],
            resources=[f"arn:aws:sagemaker:{Aws.REGION}:{Aws.ACCOUNT_ID}:endpoint/ai-trading-*"],
        ))
        return role

    def _create_strategy_agent_role(self) -> iam.Role:
        """Create least-privilege IAM role for Strategy Agent."""
        role = iam.Role(
            self,
            "StrategyAgentRole",
            role_name="ai-trading-strategy-agent-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ))
        return role

    def _create_risk_manager_role(self) -> iam.Role:
        """Create least-privilege IAM role for Risk Manager."""
        role = iam.Role(
            self,
            "RiskManagerRole",
            role_name="ai-trading-risk-manager-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ))
        return role

    def _create_order_executor_role(self) -> iam.Role:
        """Create least-privilege IAM role for Order Executor (Requirement 11.6)."""
        role = iam.Role(
            self,
            "OrderExecutorRole",
            role_name="ai-trading-order-executor-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ))
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["logs:PutLogEvents"],
            resources=[self.observability_stack.trade_executions_audit_log.log_group_arn + ":*"],
        ))
        return role

    def _create_position_manager_role(self) -> iam.Role:
        """Create least-privilege IAM role for Position Manager."""
        role = iam.Role(
            self,
            "PositionManagerRole",
            role_name="ai-trading-position-manager-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaVPCAccessExecutionRole"
        ))
        return role

    def _create_websocket_role(self) -> iam.Role:
        """Create IAM role for WebSocket handlers."""
        role = iam.Role(
            self,
            "WebSocketRole",
            role_name="ai-trading-websocket-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        ))
        return role
