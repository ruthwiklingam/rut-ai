import { SSTConfig } from "sst";
import { Bucket, Table } from "sst/constructs";
import { Function, FunctionProps } from "sst/constructs";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as cdk from "aws-cdk-lib";

export default {
  config(_input) {
    return {
      name: "ruth-ai",
      region: "us-east-1",
      profile: "awsdev",
    };
  },
  stacks(app) {
    app.stack(function Stack({ stack }) {
      const table = new Table(stack, "ChatHistory", {
        fields: {
          sessionId: "string",
          timestamp: "number",
        },
        primaryIndex: { partitionKey: "sessionId", sortKey: "timestamp" },
      });
      const bucket = new Bucket(stack, "Documents");

      // Cognito User Pool
      const userPool = new cognito.UserPool(stack, "UserPool", {
        selfSignUpEnabled: true,
        signInAliases: { email: true },
        autoVerify: { email: true },
        passwordPolicy: {
          minLength: 8,
          requireUppercase: true,
          requireLowercase: true,
          requireDigits: true,
          requireSymbols: false,
        },
        accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });

      const userPoolClient = new cognito.UserPoolClient(stack, "UserPoolClient", {
        userPool,
        authFlows: { userPassword: true, userSrp: true },
        generateSecret: false,
      });

      // Ingestion Lambda function
      const ingest = new Function(stack, "IngestFn", { 
        handler: "src/ingest.handler",
        runtime: "python3.11",
        timeout: "60 seconds",
        python: {
          installCommands: [
            "pip install --platform manylinux2014_x86_64 --only-binary=:all: -r requirements.txt -t ."
          ],
        },
        environment:{
          GEMINI_API_KEY: process.env.GEMINI_API_KEY!,
          PINECONE_API_KEY: process.env.PINECONE_API_KEY!,
          PINECONE_INDEX: "ruth-documents",
        },
        permissions: [table, bucket],
      });
      
      // connect Bucket to Lambda
      bucket.addNotifications(stack, {
        upload: {
          function: ingest,
          events: ["object_created"],
        },
      })
      
      // Upload Lambda function
      const upload = new Function(stack, "UploadFn", {
        handler: "src/upload.handler",
        runtime: "python3.11",
        permissions: [bucket],
        python: {
          installCommands: [
            "pip install --platform manylinux2014_x86_64 --only-binary=:all: -r requirements.txt -t ."
          ],
        },
        timeout: 30,
        url: {
          authorizer: "none",
        },
        environment: {
          BUCKET_NAME: bucket.bucketName,
          COGNITO_USER_POOL_ID: userPool.userPoolId,
          COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
          COGNITO_REGION: stack.region,
        },
      });

      // Chat Lambda function
      const chat = new Function(stack, "ChatBot", {
        handler: "src/chat.handler",
        runtime: "python3.11",
        permissions: [table],
        python: {
          installCommands: [
            "pip install --platform manylinux2014_x86_64 --only-binary=:all: -r requirements.txt -t ."
          ],
        },
        timeout: 30,
        url: {
          authorizer: "none",
        },
        environment: {
          GEMINI_API_KEY: process.env.GEMINI_API_KEY!,
          TABLE_NAME: table.tableName,
          PINECONE_API_KEY: process.env.PINECONE_API_KEY!,
          PINECONE_INDEX: "ruth-documents",
          COGNITO_USER_POOL_ID: userPool.userPoolId,
          COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
          COGNITO_REGION: stack.region,
        },
        nodejs: {
          install: [],
        },
      });

      stack.addOutputs({
        APIEndpoint: chat.url,
        UploadEndpoint: upload.url,
        BucketName: bucket.bucketName,
        UserPoolId: userPool.userPoolId,
        UserPoolClientId: userPoolClient.userPoolClientId,
      });
    });
  },
} satisfies SSTConfig;