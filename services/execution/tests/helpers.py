"""Seeding + signing helpers for the execution adapter tests."""

from __future__ import annotations

from at_shared.models import Agent, Transaction
from at_shared.schemas.tx import ChainId
from at_shared.uuid7 import uuid7
from eth_account import Account
from eth_account.signers.local import LocalAccount
from execution_service.validation import CHAIN_IDS

CHAIN = ChainId.BASE
EIP155 = CHAIN_IDS[CHAIN]


def make_account() -> LocalAccount:
    return Account.create()


def seed_agent(session_factory, *, org_id: str, wallet: str) -> str:
    with session_factory() as s:
        agent = Agent(
            id=uuid7(),
            org_id=org_id,
            name="exec-agent",
            wallet_address=wallet,
        )
        s.add(agent)
        s.commit()
        return agent.id


def seed_transaction(
    session_factory,
    *,
    org_id: str,
    wallet: str,
    to_address: str | None = "0x" + "2" * 40,
    value_wei: int = 1000,
    calldata: str | None = "0x",
    gas_limit: int | None = 21000,
    gas_price_wei: int | None = 1_000_000_000,
    status: str = "approved",
    nonce: int | None = None,
) -> str:
    agent_id = seed_agent(session_factory, org_id=org_id, wallet=wallet)
    with session_factory() as s:
        tx = Transaction(
            id=uuid7(),
            agent_id=agent_id,
            org_id=org_id,
            chain_id=CHAIN.value,
            from_address=wallet.lower(),
            to_address=to_address,
            value_wei=value_wei,
            raw_params={},
            calldata=calldata,
            gas_limit=gas_limit,
            gas_price_wei=gas_price_wei,
            decision="approve",
            status=status,
            nonce=nonce,
        )
        s.add(tx)
        s.commit()
        return tx.id


def sign_tx(
    account: LocalAccount,
    *,
    nonce: int,
    to: str,
    value: int = 1000,
    data: str = "0x",
    gas: int = 21000,
    gas_price: int = 1_000_000_000,
    chain_id: int = EIP155,
) -> str:
    """Sign a legacy tx and return the raw hex (0x-prefixed)."""
    signed = account.sign_transaction(
        {
            "chainId": chain_id,
            "nonce": nonce,
            "to": to,
            "value": value,
            "data": data,
            "gas": gas,
            "gasPrice": gas_price,
        }
    )
    return "0x" + signed.raw_transaction.hex()


class FakeRPC:
    """Records broadcast calls and serves canned receipts/blocks."""

    def __init__(
        self,
        *,
        tx_hash: str = "0x" + "a" * 64,
        receipt: dict | None = None,
        block_number: int = 10,
    ) -> None:
        self.broadcast_raw: list[str] = []
        self.tx_hash = tx_hash
        self.receipt = receipt
        self.block_number = block_number

    async def send_raw_transaction(self, raw: str) -> str:
        self.broadcast_raw.append(raw)
        return self.tx_hash

    async def get_transaction_receipt(self, tx_hash: str) -> dict | None:
        return self.receipt

    async def get_block_number(self) -> int:
        return self.block_number


def receipt(block: int) -> dict:
    return {"blockNumber": hex(block)}
