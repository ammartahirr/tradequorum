"""
Database Stack for AI Trading System.

Creates DynamoDB tables for signals, trade decisions, and trade records with:
- Encryption at rest (Requirement 11.3)
- DAX cache for hot signal data (Requirement 9.4)
- Timestream database for OHLCV market data (Requirement 9.5)

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 11.3
"""
from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_dynamodb as dynamodb,
    aws_dax as dax,
    aws_timestream as timestream,
    aws_iam as iam,
    aws_ec2 as ec2,
    CfnOutput,
)
from constructs import Construct


class DatabaseStack(Stack):
    """DynamoDB tables, DAX cache, and Timestream for AI Trading System."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = vpc

        # ============================================================
        # DynamoDB Tables with Encryption at Rest (Requirement 11.3)
        # ============================================================

        # Signals Table - stores NewsSignals and TechnicalSignals
        # Requirements: 9.1, 9.2
        self.signals_table = dynamodb.Table(
            self,
            "SignalsTable",
            table_name="ai-trading-signals",
            partition_key=dynamodb.Attribute(
                name="signal_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,  # Requirement 11.3
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
            time_to_live_attribute="ttl",
        )

        # GSI for querying signals by symbol
        self.signals_table.add_global_secondary_index(
            index_name="symbol-timestamp-index",
            partition_key=dynamodb.Attribute(
                name="symbol",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for querying signals by agent type
        self.signals_table.add_global_secondary_index(
            index_name="agent-type-index",
            partition_key=dynamodb.Attribute(
                name="agent_type",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Trade Decisions Table - stores Strategy Agent decisions
        # Requirement: 9.3
        self.trade_decisions_table = dynamodb.Table(
            self,
            "TradeDecisionsTable",
            table_name="ai-trading-decisions",
            partition_key=dynamodb.Attribute(
                name="decision_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,  # Requirement 11.3
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for querying decisions by symbol
        self.trade_decisions_table.add_global_secondary_index(
            index_name="symbol-timestamp-index",
            partition_key=dynamodb.Attribute(
                name="symbol",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Trade Records Table - stores executed trades
        # Requirement: 6.2
        self.trade_records_table = dynamodb.Table(
            self,
            "TradeRecordsTable",
            table_name="ai-trading-records",
            partition_key=dynamodb.Attribute(
                name="trade_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="opened_at",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,  # Requirement 11.3
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # GSI for querying trades by symbol
        self.trade_records_table.add_global_secondary_index(
            index_name="symbol-opened-index",
            partition_key=dynamodb.Attribute(
                name="symbol",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="opened_at",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI for querying trades by status
        self.trade_records_table.add_global_secondary_index(
            index_name="status-opened-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="opened_at",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # DAX Cluster for Hot Signal Data (Requirement 9.4)
        # ============================================================

        # DAX IAM Role
        dax_role = iam.Role(
            self,
            "DaxRole",
            assumed_by=iam.ServicePrincipal("dax.amazonaws.com"),
            description="IAM role for DAX cluster",
        )

        # Grant DAX access to DynamoDB tables
        self.signals_table.grant_read_write_data(dax_role)
        self.trade_decisions_table.grant_read_data(dax_role)

        # DAX Subnet Group
        private_subnets = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        dax_subnet_group = dax.CfnSubnetGroup(
            self,
            "DaxSubnetGroup",
            subnet_group_name="ai-trading-dax-subnet-group",
            subnet_ids=private_subnets.subnet_ids,
            description="Subnet group for DAX cluster",
        )

        # DAX Parameter Group
        dax_parameter_group = dax.CfnParameterGroup(
            self,
            "DaxParameterGroup",
            parameter_group_name="ai-trading-dax-params",
            description="Parameter group for DAX cluster",
            parameter_name_values={
                "query-ttl-millis": "300000",  # 5 minutes query cache
                "record-ttl-millis": "300000",  # 5 minutes item cache
            },
        )

        # DAX Cluster
        # Requirement: 9.4 - DAX cache for hot signal data
        self.dax_cluster = dax.CfnCluster(
            self,
            "DaxCluster",
            cluster_name="ai-trading-dax",
            iam_role_arn=dax_role.role_arn,
            node_type="dax.t3.small",
            replication_factor=2,  # 2 nodes for high availability
            subnet_group_name=dax_subnet_group.subnet_group_name,
            parameter_group_name=dax_parameter_group.parameter_group_name,
            sse_specification=dax.CfnCluster.SSESpecificationProperty(
                sse_enabled=True,  # Encryption at rest
            ),
            description="DAX cluster for caching hot signal data",
        )

        self.dax_cluster.add_dependency(dax_subnet_group)
        self.dax_cluster.add_dependency(dax_parameter_group)

        # ============================================================
        # Timestream Database for Market Data (Requirement 9.5)
        # ============================================================

        # Timestream Database
        self.timestream_database = timestream.CfnDatabase(
            self,
            "TimestreamDatabase",
            database_name="ai-trading-market-data",
        )

        # Timestream Table for OHLCV Candles
        # Requirement: 9.5 - Store OHLCV candles in Timestream
        self.ohlcv_table = timestream.CfnTable(
            self,
            "OhlcvTable",
            database_name=self.timestream_database.database_name,
            table_name="ohlcv-candles",
            retention_properties={
                "MemoryStoreRetentionPeriodInHours": "24",  # 24 hours in memory
                "MagneticStoreRetentionPeriodInDays": "1825",  # 5 years on disk
            },
            magnetic_store_write_properties={
                "EnableMagneticStoreWrites": True,
            },
        )

        self.ohlcv_table.add_dependency(self.timestream_database)

        # ============================================================
        # Outputs
        # ============================================================

        CfnOutput(
            self,
            "SignalsTableName",
            value=self.signals_table.table_name,
            description="DynamoDB table for signals",
        )

        CfnOutput(
            self,
            "TradeDecisionsTableName",
            value=self.trade_decisions_table.table_name,
            description="DynamoDB table for trade decisions",
        )

        CfnOutput(
            self,
            "TradeRecordsTableName",
            value=self.trade_records_table.table_name,
            description="DynamoDB table for trade records",
        )

        CfnOutput(
            self,
            "DaxClusterEndpoint",
            value=self.dax_cluster.attr_cluster_discovery_endpoint,
            description="DAX cluster endpoint",
        )

        CfnOutput(
            self,
            "TimestreamDatabaseName",
            value=self.timestream_database.database_name or "ai-trading-market-data",
            description="Timestream database for market data",
        )
