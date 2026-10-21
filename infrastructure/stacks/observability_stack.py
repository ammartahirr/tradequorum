"""
Observability Stack for AI Trading System.

Creates:
- CloudWatch Log Groups for error logging with sufficient context (Requirement 10.5)
- Tamper-evident audit trail for trade decisions and executions (Requirement 11.8)

Requirements: 10.5, 11.8
"""
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_logs as logs,
    aws_kms as kms,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class ObservabilityStack(Stack):
    """CloudWatch logging and audit trails for AI Trading System."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================
        # KMS Key for Log Encryption (Tamper-evident audit trail)
        # ============================================================

        # KMS key for encrypting audit logs
        # Requirement: 11.8 - Tamper-evident audit trail
        self.audit_log_key = kms.Key(
            self,
            "AuditLogKey",
            alias="ai-trading/audit-logs",
            description="KMS key for encrypting audit logs",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Grant CloudWatch Logs permission to use the key
        self.audit_log_key.grant_encrypt_decrypt(
            iam.ServicePrincipal(
                f"logs.{Stack.of(self).region}.amazonaws.com"
            )
        )

        # ============================================================
        # CloudWatch Log Groups (Requirement 10.5)
        # ============================================================

        # News Agent Log Group
        self.news_agent_log_group = logs.LogGroup(
            self,
            "NewsAgentLogGroup",
            log_group_name="/ai-trading/agents/news",
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Technical Agent Log Group
        self.technical_agent_log_group = logs.LogGroup(
            self,
            "TechnicalAgentLogGroup",
            log_group_name="/ai-trading/agents/technical",
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Strategy Agent Log Group
        self.strategy_agent_log_group = logs.LogGroup(
            self,
            "StrategyAgentLogGroup",
            log_group_name="/ai-trading/agents/strategy",
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Risk Manager Log Group
        self.risk_manager_log_group = logs.LogGroup(
            self,
            "RiskManagerLogGroup",
            log_group_name="/ai-trading/execution/risk-manager",
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Order Executor Log Group
        self.order_executor_log_group = logs.LogGroup(
            self,
            "OrderExecutorLogGroup",
            log_group_name="/ai-trading/execution/order-executor",
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Position Manager Log Group
        self.position_manager_log_group = logs.LogGroup(
            self,
            "PositionManagerLogGroup",
            log_group_name="/ai-trading/execution/position-manager",
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # WebSocket API Log Group
        self.websocket_log_group = logs.LogGroup(
            self,
            "WebSocketLogGroup",
            log_group_name="/ai-trading/api/websocket",
            retention=logs.RetentionDays.SIX_MONTHS,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ============================================================
        # Tamper-Evident Audit Trail (Requirement 11.8)
        # ============================================================

        # Trade Decisions Audit Log - encrypted with KMS
        # Requirement: 11.8 - Tamper-evident audit trail for trade decisions
        self.trade_decisions_audit_log = logs.LogGroup(
            self,
            "TradeDecisionsAuditLog",
            log_group_name="/ai-trading/audit/trade-decisions",
            retention=logs.RetentionDays.FIVE_YEARS,  # Long retention for audit
            removal_policy=RemovalPolicy.RETAIN,
            encryption_key=self.audit_log_key,
        )

        # Trade Executions Audit Log - encrypted with KMS
        # Requirement: 11.8 - Tamper-evident audit trail for executions
        self.trade_executions_audit_log = logs.LogGroup(
            self,
            "TradeExecutionsAuditLog",
            log_group_name="/ai-trading/audit/trade-executions",
            retention=logs.RetentionDays.FIVE_YEARS,  # Long retention for audit
            removal_policy=RemovalPolicy.RETAIN,
            encryption_key=self.audit_log_key,
        )

        # Risk Assessments Audit Log - encrypted with KMS
        self.risk_assessments_audit_log = logs.LogGroup(
            self,
            "RiskAssessmentsAuditLog",
            log_group_name="/ai-trading/audit/risk-assessments",
            retention=logs.RetentionDays.FIVE_YEARS,
            removal_policy=RemovalPolicy.RETAIN,
            encryption_key=self.audit_log_key,
        )

        # ============================================================
        # Metric Filters for Alerting
        # ============================================================

        # Error metric filter for all agent logs
        logs.MetricFilter(
            self,
            "AgentErrorMetricFilter",
            log_group=self.strategy_agent_log_group,
            metric_namespace="AITrading/Agents",
            metric_name="AgentErrors",
            filter_pattern=logs.FilterPattern.literal("[ERROR]"),
            metric_value="1",
        )

        # Trade execution failure metric
        logs.MetricFilter(
            self,
            "TradeExecutionFailureMetric",
            log_group=self.order_executor_log_group,
            metric_namespace="AITrading/Execution",
            metric_name="TradeExecutionFailures",
            filter_pattern=logs.FilterPattern.literal("ORDER_FAILED"),
            metric_value="1",
        )

        # Risk limit breach metric
        logs.MetricFilter(
            self,
            "RiskLimitBreachMetric",
            log_group=self.risk_manager_log_group,
            metric_namespace="AITrading/Risk",
            metric_name="RiskLimitBreaches",
            filter_pattern=logs.FilterPattern.literal("RISK_LIMIT_BREACH"),
            metric_value="1",
        )

        # Daily loss limit breach metric
        logs.MetricFilter(
            self,
            "DailyLossLimitMetric",
            log_group=self.risk_manager_log_group,
            metric_namespace="AITrading/Risk",
            metric_name="DailyLossLimitBreaches",
            filter_pattern=logs.FilterPattern.literal("DAILY_LOSS_LIMIT_BREACH"),
            metric_value="1",
        )

        # ============================================================
        # Outputs
        # ============================================================

        CfnOutput(
            self,
            "AuditLogKeyArn",
            value=self.audit_log_key.key_arn,
            description="KMS key ARN for audit log encryption",
        )

        CfnOutput(
            self,
            "TradeDecisionsAuditLogArn",
            value=self.trade_decisions_audit_log.log_group_arn,
            description="Trade decisions audit log ARN",
        )

        CfnOutput(
            self,
            "TradeExecutionsAuditLogArn",
            value=self.trade_executions_audit_log.log_group_arn,
            description="Trade executions audit log ARN",
        )
