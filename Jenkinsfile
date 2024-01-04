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

                    // Map the host directory containing user_info.json to a directory inside the container
                    sh 'docker run -e DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN} -v ${WORKSPACE}:/app -d --name discord-bot-container duck-bot:${env.BUILD_ID}'
                }
            }
        }
    }
}