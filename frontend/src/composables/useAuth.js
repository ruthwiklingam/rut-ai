import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserAttribute,
} from 'amazon-cognito-identity-js';
import { ref } from 'vue';

// Lazily initialized so missing env vars don't crash at module load time
let _userPool = null;
function getUserPool() {
  if (!_userPool) {
    _userPool = new CognitoUserPool({
      UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      ClientId:   import.meta.env.VITE_COGNITO_CLIENT_ID,
    });
  }
  return _userPool;
}

// Reactive state shared across the app
export const authState = ref('loading'); // 'loading' | 'login' | 'register' | 'confirm' | 'app'
export const authError = ref('');
export const pendingEmail = ref(''); // Persists email across register -> confirm transition

// Check localStorage for an existing valid session on app startup
export function checkExistingSession() {
  const cognitoUser = getUserPool().getCurrentUser();
  if (!cognitoUser) {
    authState.value = 'login';
    return;
  }
  cognitoUser.getSession((err, session) => {
    if (err || !session.isValid()) {
      authState.value = 'login';
    } else {
      authState.value = 'app';
    }
  });
}

// Retrieve the current ID token, auto-refreshing via refresh token if needed.
// Call this before every API request.
export function getIdToken() {
  return new Promise((resolve, reject) => {
    const cognitoUser = getUserPool().getCurrentUser();
    if (!cognitoUser) {
      reject(new Error('No current user'));
      return;
    }
    cognitoUser.getSession((err, session) => {
      if (err || !session.isValid()) {
        reject(err || new Error('Session invalid'));
        return;
      }
      resolve(session.getIdToken().getJwtToken());
    });
  });
}

export function signIn(email, password) {
  authError.value = '';
  return new Promise((resolve, reject) => {
    const authDetails = new AuthenticationDetails({ Username: email, Password: password });
    const cognitoUser = new CognitoUser({ Username: email, Pool: getUserPool() });
    cognitoUser.authenticateUser(authDetails, {
      onSuccess: () => {
        authState.value = 'app';
        resolve();
      },
      onFailure: (err) => {
        authError.value = err.message || 'Sign-in failed';
        reject(err);
      },
      newPasswordRequired: () => {
        authError.value = 'Password reset required. Please contact support.';
        reject(new Error('newPasswordRequired'));
      },
    });
  });
}

export function signUp(email, password) {
  authError.value = '';
  const attributeList = [new CognitoUserAttribute({ Name: 'email', Value: email })];
  return new Promise((resolve, reject) => {
    getUserPool().signUp(email, password, attributeList, null, (err, result) => {
      if (err) {
        authError.value = err.message || 'Sign-up failed';
        reject(err);
        return;
      }
      pendingEmail.value = email;
      authState.value = 'confirm';
      resolve(result);
    });
  });
}

export function confirmRegistration(email, code) {
  authError.value = '';
  return new Promise((resolve, reject) => {
    const cognitoUser = new CognitoUser({ Username: email, Pool: getUserPool() });
    cognitoUser.confirmRegistration(code, true, (err, result) => {
      if (err) {
        authError.value = err.message || 'Confirmation failed';
        reject(err);
        return;
      }
      authState.value = 'login';
      pendingEmail.value = '';
      resolve(result);
    });
  });
}

export function signOut() {
  const cognitoUser = getUserPool().getCurrentUser();
  if (cognitoUser) cognitoUser.signOut();
  authState.value = 'login';
  authError.value = '';
}
