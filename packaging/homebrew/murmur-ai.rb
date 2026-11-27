# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.67"
  sha256 "F8C36B7BCEA5DE50A6ADAC3FE5A2F7ECB6BF0E284CDDF0F9E43773E27EA67251"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.67/Murmur.AI_1.2.67_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
