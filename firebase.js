// firebase.js

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-analytics.js";

import {
    getAuth,
    createUserWithEmailAndPassword,
    signInWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    updateProfile
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js";

import {
    getDatabase,
    ref,
    set,
    get,
    push,
    update,
    remove,
    onValue,
    serverTimestamp
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-database.js";

// =======================
// Firebase Configuration
// =======================

const firebaseConfig = {
    apiKey: "AIzaSyBq7UEsIwoudC2g8DRrG7EwqblX9SIDCF8",
    authDomain: "ticktok-7fb30.firebaseapp.com",
    databaseURL: "https://ticktok-7fb30-default-rtdb.firebaseio.com",
    projectId: "ticktok-7fb30",
    storageBucket: "ticktok-7fb30.firebasestorage.app",
    messagingSenderId: "493782050714",
    appId: "1:493782050714:web:2bda69e946d8bdfb50fc23",
    measurementId: "G-2FYPJB4Y9Y"
};

// =======================
// Initialize Firebase
// =======================

const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);

const auth = getAuth(app);
const db = getDatabase(app);

// =======================
// Export Everything
// =======================

export {
    app,
    analytics,
    auth,
    db,

    createUserWithEmailAndPassword,
    signInWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    updateProfile,

    ref,
    set,
    get,
    push,
    update,
    remove,
    onValue,
    serverTimestamp
};