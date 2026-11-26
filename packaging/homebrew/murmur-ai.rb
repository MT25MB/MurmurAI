# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.53"
  sha256 "61718C51A03F170D976D9E273387D36247414F5757BA683434D579ECB0373DE7"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.53/Murmur.AI_1.2.53_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
