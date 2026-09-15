[object Object]
    
    def test_reliable_browser_rejects_unrelated_global_listing(self) -> None:
        from src.collectors.browser_public_reliable import ReliableBrowserSearchMixin
        from src.models.tender import Tender

        tender = Tender(
            platform="fabrikant",
            external_id="1",
            title="Игра для сюжетно-ролевой игры",
            url="https://example.test/1",
            description="Поставка игрушек",
        )
        assert ReliableBrowserSearchMixin._tender_matches_query(tender, "станок") is False

    def test_reliable_browser_accepts_russian_inflection(self) -> None:
        from src.collectors.browser_public_reliable import ReliableBrowserSearchMixin
        from src.models.tender import Tender

        tender = Tender(
            platform="fabrikant",
            external_id="2",
            title="Поставка станка токарно-винторезного",
            url="https://example.test/2",
            description="",
        )
        assert ReliableBrowserSearchMixin._tender_matches_query(tender, "станок") is True
