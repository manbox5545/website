import {
    auth,
    signInWithEmailAndPassword,
    onAuthStateChanged,
    signOut
} from "./firebase.js";

const email = document.getElementById("email");
const password = document.getElementById("password");

const loginBtn = document.getElementById("loginBtn");
const logoutBtn = document.getElementById("logoutBtn");

const loginScreen = document.getElementById("loginScreen");
const app = document.getElementById("app");

// Login
loginBtn.addEventListener("click", async () => {

    const userEmail = email.value.trim();
    const userPassword = password.value;

    if (!userEmail || !userPassword) {
        alert("Enter email and password.");
        return;
    }

    try {

        await signInWithEmailAndPassword(
            auth,
            userEmail,
            userPassword
        );

        alert("Login successful!");

    } catch (err) {

        alert(err.message);

    }

});

// Logout
logoutBtn.addEventListener("click", async () => {

    await signOut(auth);

});

// Auto Login
onAuthStateChanged(auth, (user) => {

    if (user) {

        loginScreen.classList.add("hidden");
        app.classList.remove("hidden");

    } else {

        app.classList.add("hidden");
        loginScreen.classList.remove("hidden");

    }

});