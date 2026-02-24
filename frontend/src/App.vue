<template>
  <!-- LOADING -->
  <div v-if="authState === 'loading'" class="auth-container">
    <p>Loading...</p>
  </div>

  <!-- AUTH SCREENS -->
  <div v-else-if="authState !== 'app'" class="auth-container">
    <div class="auth-card">
      <h1>DocuMentor AI</h1>

      <!-- SIGN IN -->
      <form v-if="authState === 'login'" @submit.prevent="handleSignIn">
        <h2>Sign In</h2>
        <div v-if="authError" class="auth-error">{{ authError }}</div>
        <input type="email" v-model="formEmail" placeholder="Email" required autocomplete="email" />
        <input type="password" v-model="formPassword" placeholder="Password" required autocomplete="current-password" />
        <button type="submit" :disabled="isAuthLoading">
          {{ isAuthLoading ? 'Signing in...' : 'Sign In' }}
        </button>
        <p class="auth-switch">
          Don't have an account?
          <a href="#" @click.prevent="goToRegister">Create one</a>
        </p>
      </form>

      <!-- SIGN UP -->
      <form v-else-if="authState === 'register'" @submit.prevent="handleSignUp">
        <h2>Create Account</h2>
        <div v-if="authError" class="auth-error">{{ authError }}</div>
        <input type="email" v-model="formEmail" placeholder="Email" required autocomplete="email" />
        <input type="password" v-model="formPassword" placeholder="Password (8+ chars, upper, lower, digit)" required autocomplete="new-password" />
        <button type="submit" :disabled="isAuthLoading">
          {{ isAuthLoading ? 'Creating account...' : 'Create Account' }}
        </button>
        <p class="auth-switch">
          Already have an account?
          <a href="#" @click.prevent="goToLogin">Sign in</a>
        </p>
      </form>

      <!-- CONFIRM EMAIL -->
      <form v-else-if="authState === 'confirm'" @submit.prevent="handleConfirm">
        <h2>Verify Email</h2>
        <p class="auth-info">A verification code was sent to <strong>{{ pendingEmail }}</strong>.</p>
        <div v-if="authError" class="auth-error">{{ authError }}</div>
        <input type="text" v-model="confirmCode" placeholder="6-digit code" required inputmode="numeric" maxlength="6" />
        <button type="submit" :disabled="isAuthLoading">
          {{ isAuthLoading ? 'Verifying...' : 'Verify Email' }}
        </button>
      </form>
    </div>
  </div>

  <!-- MAIN APP -->
  <div v-else id="chat-container">
    <h1>
      Chat with your documents
      <button class="logout-btn" @click="handleSignOut">Sign Out</button>
    </h1>

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

<script setup>
import { ref, onMounted } from 'vue';
import {
  authState, authError, pendingEmail,
  checkExistingSession, signIn, signUp,
  confirmRegistration, signOut, getIdToken,
} from './composables/useAuth.js';

// --- Auth form state ---
const formEmail     = ref('');
const formPassword  = ref('');
const confirmCode   = ref('');
const isAuthLoading = ref(false);

// --- App state ---
const userInput    = ref('');
const chatHistory  = ref([]);
const isLoading    = ref(false);
const sessionId    = `session-${Date.now()}`;
const selectedFile = ref(null);
const isUploading  = ref(false);
const uploadStatus = ref(null);
const fileInput    = ref(null);

onMounted(() => {
  checkExistingSession();
});

// --- Auth handlers ---
function goToRegister() {
  authError.value = '';
  formEmail.value = '';
  formPassword.value = '';
  authState.value = 'register';
}

function goToLogin() {
  authError.value = '';
  formEmail.value = '';
  formPassword.value = '';
  authState.value = 'login';
}

async function handleSignIn() {
  isAuthLoading.value = true;
  try {
    await signIn(formEmail.value, formPassword.value);
    formEmail.value = '';
    formPassword.value = '';
  } finally {
    isAuthLoading.value = false;
  }
}

async function handleSignUp() {
  isAuthLoading.value = true;
  try {
    await signUp(formEmail.value, formPassword.value);
    formPassword.value = '';
  } finally {
    isAuthLoading.value = false;
  }
}

async function handleConfirm() {
  isAuthLoading.value = true;
  try {
    await confirmRegistration(pendingEmail.value, confirmCode.value);
    confirmCode.value = '';
  } finally {
    isAuthLoading.value = false;
  }
}

function handleSignOut() {
  signOut();
}

// --- API helper ---
async function getAuthHeaders() {
  const token = await getIdToken();
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };
}

// --- App methods ---
function handleFileSelect(event) {
  selectedFile.value = event.target.files[0];
  uploadStatus.value = null;
}

async function uploadFile() {
  if (!selectedFile.value) return;
  isUploading.value = true;
  uploadStatus.value = null;
  try {
    const file = selectedFile.value;
    const contentType = file.type || 'application/octet-stream';

    // Step 1: Get a pre-signed S3 URL from the Lambda (authenticated)
    const headers = await getAuthHeaders();
    const response = await fetch(import.meta.env.VITE_UPLOAD_API_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({ filename: file.name, contentType }),
    });

    if (!response.ok) {
      if (response.status === 401) { signOut(); return; }
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const { uploadUrl } = await response.json();

    // Step 2: PUT the raw file directly to S3 — bypasses Lambda's 6 MB limit
    const s3Response = await fetch(uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': contentType },
      body: file,
    });

    if (!s3Response.ok) {
      throw new Error(`S3 upload failed: ${s3Response.status}`);
    }

    uploadStatus.value = {
      type: 'success',
      message: `Document "${file.name}" uploaded successfully! It will be processed and available for chat shortly.`,
    };
    selectedFile.value = null;
    fileInput.value.value = '';
  } catch (error) {
    console.error('Error uploading file:', error);
    uploadStatus.value = { type: 'error', message: 'Failed to upload document. Please try again.' };
  } finally {
    isUploading.value = false;
  }
}

async function sendMessage() {
  if (!userInput.value.trim()) return;
  const userMessage = { role: 'user', content: userInput.value, timestamp: Date.now() };
  chatHistory.value.push(userMessage);
  isLoading.value = true;
  try {
    const headers = await getAuthHeaders();
    const response = await fetch(import.meta.env.VITE_CHAT_API_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message: userInput.value, sessionId }),
    });

    if (!response.ok) {
      if (response.status === 401) { signOut(); return; }
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    chatHistory.value.push({
      role: 'assistant',
      content: data.response,
      sources: data.sources,
      timestamp: Date.now(),
    });
  } catch (error) {
    console.error('Error sending message:', error);
    chatHistory.value.push({
      role: 'assistant',
      content: 'Sorry, I had trouble getting a response. Please try again.',
      timestamp: Date.now(),
    });
  } finally {
    userInput.value = '';
    isLoading.value = false;
  }
}
</script>
