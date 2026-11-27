# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.71"
  sha256 "5957B104431B15DCF987C2C4F9FB218E96136585369147A6C03ABE24552D339B"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.71/Murmur.AI_1.2.71_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
