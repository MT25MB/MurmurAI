import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import CursorOverlay from "./components/CursorOverlay";
import "./index.css";

const isCursorOverlay = new URLSearchParams(window.location.search).get("overlay") === "cursor";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isCursorOverlay ? <CursorOverlay /> : <App />}
  </React.StrictMode>,
);
