"""Convert mbox to maildir."""
import mailbox
import sys
from pathlib import Path


def convert_mbox_to_maildir(path: Path) -> None:
    """Convert mbox to maildir."""
    directory = path.parent / "{path.name}.d"
    for folder in ("tmp", "new", "cur"):
        (directory / folder).mkdir(parents=True)

    mbox = mailbox.mbox(path)
    maildir = mailbox.Maildir(directory)
    for index, message in enumerate(mbox):
        subject = message.get("Subject", "")
        print(f"{index:-8d} {subject}", file=sys.stderr)
        maildir.add(message)


def main() -> None:
    """Main entry point."""
    for arg in sys.argv[1:]:
        convert_mbox_to_maildir(Path(arg))


if __name__ == "__main__":
    main()
