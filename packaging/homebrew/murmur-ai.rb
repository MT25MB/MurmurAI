# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.79"
  sha256 "70100394E21D893E9649A2B8BB08405F4D1595E6B8F656866A96CEF6FAC460C5"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.79/Murmur.AI_1.2.79_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
