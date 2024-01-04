pipeline {
    agent any

    environment {
        // token stored in Jenkins credentials
        DISCORD_BOT_TOKEN = credentials('duck-bot-token')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Build Docker Image') {
            steps {
                script {
                    dockerImage = docker.build("duck-bot:${env.BUILD_ID}")
                }
            }
        }
        stage('Run Docker Container') {
            steps {
                script {
                    // Stop and remove the existing container if it exists
                    sh 'docker stop discord-bot-container || true'
                    sh 'docker rm discord-bot-container || true'

                    // Create the volume if it doesn't exist
                    sh 'docker volume create duck-bot-data || true'

                    // Pass the Discord bot token as an environment variable to the Docker container
                    // Mount the volume to persist the user_info.json file
                    dockerImage.run("-e DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN} -v duck-bot-data:/app/data -d --name discord-bot-container")
                }
            }
        }
    }
}
