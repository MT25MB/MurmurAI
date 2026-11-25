# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.37"
  sha256 "E46A0F343679D9C8F39E8BC68D7BDCD2B1615FDBC3569D2D0513F2B30A71A54E"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.37/Murmur.AI_1.2.37_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
