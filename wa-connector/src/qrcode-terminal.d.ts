declare module "qrcode-terminal" {
  export function generate(
    text: string,
    opts?: { small?: boolean },
    callback?: (err: unknown, url: string) => void
  ): void;
}
