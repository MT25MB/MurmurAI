# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.19"
  sha256 "6A8BA03ECFFAF701CDF4EF1E35B650726CBBB5BD86440D4DE254FBA87AC5BEF6"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.19/Murmur.AI_1.2.19_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
