# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.64"
  sha256 "8254EC2530794F77F96001ADA7F4B615660DBD5D2221575DE81C5EFCD3BC4B9A"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.64/Murmur.AI_1.2.64_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
