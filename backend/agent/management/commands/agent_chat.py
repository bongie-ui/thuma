"""Talk to the agent from the terminal (manual testing). One message per call; history is kept."""

import mimetypes
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Family
from agent import chat
from agent.models import Conversation
from core.phones import normalize_phone
from mandates import services


class Command(BaseCommand):
    help = "Send one chat message as a funder (--user) or a phone number (--phone) and print the reply."

    def add_arguments(self, parser):
        parser.add_argument("message")
        parser.add_argument("--family", required=True, help="family name")
        who = parser.add_mutually_exclusive_group(required=True)
        who.add_argument("--user", help="username of a funder")
        who.add_argument("--phone", help="phone number of a beneficiary, payee or unknown sender")
        parser.add_argument("--attach", action="append", default=[], help="image file to attach (repeatable)")

    def handle(self, message, family, user=None, phone=None, attach=(), **options):
        family = Family.objects.filter(name=family).first() or self._missing(f"family {family!r}")
        if user:
            participant = get_user_model().objects.filter(username=user).first() or self._missing(f"user {user!r}")
            conversation, _ = Conversation.objects.get_or_create(family=family, participant_user=participant)
        else:
            phone = normalize_phone(phone) or self._missing(f"valid phone {phone!r}")
            conversation, _ = Conversation.objects.get_or_create(family=family, participant_phone=phone,
                                                                 participant_user=None)
        uploads = []
        for path in map(Path, attach):
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            uploads.append(services.create_upload(family=family, data=path.read_bytes(), content_type=content_type,
                                                  name=path.name, user=conversation.participant_user, phone=phone or ""))
        reply = chat.run_turn(conversation, message, uploads=uploads)
        self.stdout.write(reply.text)
        if reply.linked_request:
            r = reply.linked_request
            self.stdout.write(self.style.NOTICE(f"[request {r.id}: {r.status}, {r.amount} {r.product}]"))

    def _missing(self, what):
        raise CommandError(f"No {what}")
