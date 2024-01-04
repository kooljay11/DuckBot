pipeline {
    agent any

    environment {
        // token stored in Jenkins credentials
        DISCORD_BOT_TOKEN = credentials('duck-bot-token')
    }

    stages {
        stage('Delete Existing Container') {
            steps {
                script {
                    // Remove existing container if it exists
                    sh "docker rm -f discord-bot-container || true"
                }
            }
        }
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
                    // Pass the Discord bot token as an environment variable to the Docker container
                    dockerImage.run("-e DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN} -d --name discord-bot-container")
                }
            }
        }
    }
}
