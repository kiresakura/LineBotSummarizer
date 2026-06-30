# Security Policy

## 回報漏洞 / Reporting a Vulnerability

如果你發現安全漏洞，**請勿開公開 Issue**。請改用 GitHub 的私密回報管道：

> Repository → **Security** → **Report a vulnerability**（GitHub Private Vulnerability Reporting）

我們會盡快確認並修復。請提供：重現步驟、影響範圍、可能的修補建議。

## 運營者須知 / Operator Notes

本專案會處理 LINE 群組中的**第三方個人訊息**並送往外部 AI 服務，自行部署前請務必注意：

- **金鑰管理**：所有金鑰僅透過環境變數注入，**切勿** commit `.env` 或將其放入 Docker image。
- **網路存取（SSRF）**：本服務會抓取使用者貼出的 URL。程式已內建私有網段封鎖
  （見 `lorekeeper/services/safe_http.py`），但仍建議在部署環境施加 egress 網路政策作為縱深防禦。
- **個資 / 合規**：擷取群組成員訊息、圖片、語音前，請取得成員**知情同意**，
  並評估當地個資法規（如台灣《個人資料保護法》）。AI 供應商的資料留存政策亦需確認。
- **存取控制**：Webhook 端點受 LINE 簽章驗證保護；請勿停用，且 `LINE_CHANNEL_SECRET` 不可留空。

## 支援版本 / Supported Versions

本專案目前處於早期階段（`0.x`），安全修補僅提供給最新版本。
