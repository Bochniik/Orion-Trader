import { useEffect, useState } from "react";
import { Bell, Download } from "lucide-react";

export default function PwaControls({ showNotifications = true }) {
  const [prompt, setPrompt] = useState(null); const [notifications, setNotifications] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  useEffect(() => { const handler = (event) => { event.preventDefault(); setPrompt(event); }; window.addEventListener("beforeinstallprompt", handler); return () => window.removeEventListener("beforeinstallprompt", handler); }, []);
  async function install() { if (prompt) { await prompt.prompt(); setPrompt(null); } }
  async function enableNotifications() { if (typeof Notification !== "undefined") setNotifications(await Notification.requestPermission()); }
  return <div className="pwa-controls">{prompt && <button className="ghost-btn" type="button" onClick={install}><Download size={14} /> Install app</button>}{showNotifications && notifications === "default" && <button className="ghost-btn" type="button" onClick={enableNotifications}><Bell size={14} /> Enable alerts</button>}</div>;
}
