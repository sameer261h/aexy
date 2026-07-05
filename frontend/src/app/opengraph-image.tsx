import { ImageResponse } from "next/og";

export const alt = "Aexy — The AI Company OS";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "96px",
          background: "#08090d",
          backgroundImage:
            "radial-gradient(circle at 12% 8%, rgba(45,212,191,0.22), transparent 42%), radial-gradient(circle at 88% 96%, rgba(168,85,247,0.20), transparent 40%)",
          color: "#ffffff",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "24px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "88px",
              height: "88px",
              borderRadius: "22px",
              background: "#ffffff",
            }}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#08090d" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
          </div>
          <div style={{ fontSize: "64px", fontWeight: 700, letterSpacing: "-0.03em" }}>
            Aexy
          </div>
        </div>
        <div
          style={{
            marginTop: "56px",
            fontSize: "76px",
            fontWeight: 700,
            letterSpacing: "-0.03em",
            lineHeight: 1.05,
          }}
        >
          The AI Company OS
        </div>
        <div
          style={{
            marginTop: "36px",
            fontSize: "34px",
            fontWeight: 500,
            color: "rgba(255,255,255,0.66)",
          }}
        >
          engineering · CRM · GTM · people · docs · agents
        </div>
      </div>
    ),
    { ...size },
  );
}
