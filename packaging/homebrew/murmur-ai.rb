# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.43"
  sha256 "874811B3CBB82787D785B50E35EBDCD25CF2AAA4F684B3FDBFCF94BE8344FE80"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.43/Murmur.AI_1.2.43_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
