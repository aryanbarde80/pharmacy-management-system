// Firebase configuration for client-side authentication
// This should be your web app config from Firebase Console > Project Settings > General > Web apps
const firebaseConfig = {
  apiKey: "AIzaSyCFvbQU6h5-18NMKtWjgpCCoPWxpi76pBk",
  authDomain: "pharmacy-managment-4b55f.firebaseapp.com",
  projectId: "pharmacy-managment-4b55f",
  storageBucket: "pharmacy-managment-4b55f.appspot.com",
  messagingSenderId: "473321404811",
  appId: "1:473321404811:web:4707ce0075e069a80ad78e",
  measurementId: "G-9EESYMDYQS"
};

// Initialize Firebase
firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();

// Export for use in other files
window.firebaseAuth = auth;
window.firebaseConfig = firebaseConfig;
