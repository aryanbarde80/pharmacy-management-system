// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyDwH8jipZvnVneqDCi7xsroH6b8d7uBhJ8",
  authDomain: "pharma-e06d0.firebaseapp.com",
  projectId: "pharma-e06d0",
  storageBucket: "pharma-e06d0.firebasestorage.app",
  messagingSenderId: "276212911327",
  appId: "1:276212911327:web:0ef0b0682ddb7197a1ad6a",
  measurementId: "G-DVTJ0VM3TK"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);
