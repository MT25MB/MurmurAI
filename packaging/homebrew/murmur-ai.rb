# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.76"
  sha256 "1A806126A0036477985F8ADD6A5D4D8E6F2F7646247E6F4678253EDF694D7F2C"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.76/Murmur.AI_1.2.76_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
