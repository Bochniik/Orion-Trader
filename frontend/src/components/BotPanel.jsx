import { Bot } from "lucide-react";

export default function BotPanel({ botResult }) {
  if (!botResult) {
    return null;
  }

  return (
    <section className="card">
      <div className="card-title">
        <Bot size={20} />
        Bot result
      </div>

      <p>
        <b>Action taken:</b> {botResult.action_taken}
      </p>

      <p>
        <b>Signal detected:</b> {botResult.signal}
      </p>
    </section>
  );
}