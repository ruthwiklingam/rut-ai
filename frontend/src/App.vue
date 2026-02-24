<template>
  <div id="chat-container">
    <h1>Chat with your documents</h1>
    
    <!-- File Upload Section -->
    <div id="upload-section">
      <div class="upload-form">
        <input 
          ref="fileInput"
          type="file" 
          accept=".pdf,.doc,.docx,.txt"
          @change="handleFileSelect"
          :disabled="isUploading"
        >
        <button 
          @click="uploadFile" 
          :disabled="!selectedFile || isUploading"
          class="upload-btn"
        >
          {{ isUploading ? 'Uploading...' : 'Upload Document' }}
        </button>
      </div>
      <div v-if="uploadStatus" :class="['upload-status', uploadStatus.type]">
        {{ uploadStatus.message }}
      </div>
    </div>
    
    <div id="chat-history">
      <div v-for="message in chatHistory" :key="message.timestamp" :class="['message', message.role]">
        <p>{{ message.content }}</p>
        <div v-if="message.sources" class="sources">
          <strong>Sources:</strong>
          <ul>
            <li v-for="source in message.sources" :key="source.source">
              {{ source.source }} (Score: {{ source.score.toFixed(2) }})
            </li>
          </ul>
        </div>
      </div>
    </div>
    <form @submit.prevent="sendMessage">
      <input type="text" v-model="userInput" placeholder="Ask a question..." :disabled="isLoading">
      <button type="submit" :disabled="isLoading">{{ isLoading ? 'Thinking...' : 'Send' }}</button>
    </form>
  </div>
</template>

<script>
export default {
  data() {
    return {
      userInput: '',
      chatHistory: [],
      isLoading: false,
      sessionId: `session-${Date.now()}`,
      selectedFile: null,
      isUploading: false,
      uploadStatus: null,
      uploadEndpoint: import.meta.env.VITE_UPLOAD_API_URL
    };
  },
  methods: {
    handleFileSelect(event) {
      this.selectedFile = event.target.files[0];
      this.uploadStatus = null;
    },

    async uploadFile() {
      if (!this.selectedFile) return;
      
      this.isUploading = true;
      this.uploadStatus = null;
      
      try {
        // Convert file to base64
        const fileReader = new FileReader();
        const fileData = await new Promise((resolve) => {
          fileReader.onload = () => resolve(fileReader.result);
          fileReader.readAsDataURL(this.selectedFile);
        });
        
        // Remove the data URL prefix to get just the base64 content
        const base64Content = fileData.split(',')[1];
        
        const response = await fetch(this.uploadEndpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            file: base64Content,
            filename: this.selectedFile.name,
            contentType: this.selectedFile.type
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        this.uploadStatus = {
          type: 'success',
          message: `Document "${this.selectedFile.name}" uploaded successfully! It will be processed and available for chat shortly.`
        };
        
        // Clear the file input
        this.selectedFile = null;
        this.$refs.fileInput.value = '';
        
      } catch (error) {
        console.error('Error uploading file:', error);
        this.uploadStatus = {
          type: 'error',
          message: 'Failed to upload document. Please try again.'
        };
      } finally {
        this.isUploading = false;
      }
    },

    async sendMessage() {
      if (!this.userInput.trim()) return;

      const userMessage = {
        role: 'user',
        content: this.userInput,
        timestamp: Date.now()
      };
      this.chatHistory.push(userMessage);
      this.isLoading = true;

      try {
        const response = await fetch(import.meta.env.VITE_CHAT_API_URL, { 
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: this.userInput,
            sessionId: this.sessionId
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        const aiMessage = {
          role: 'assistant',
          content: data.response,
          sources: data.sources,
          timestamp: Date.now()
        };
        this.chatHistory.push(aiMessage);

      } catch (error) {
        console.error('Error sending message:', error);
        const errorMessage = {
          role: 'assistant',
          content: 'Sorry, I had trouble getting a response. Please try again.',
          timestamp: Date.now()
        };
        this.chatHistory.push(errorMessage);
      } finally {
        this.userInput = '';
        this.isLoading = false;
      }
    }
  }
};
</script>