from __future__ import annotations

from bin_finder.models import CandidateRecord, SceneContext, SceneRecord


def demo_scenes() -> list[SceneRecord]:
    return [
        SceneRecord(
            scene_id="scene_001",
            order=1,
            english_text=(
                "At dawn in Havana, an elderly Cuban mechanic repairs a faded 1955 Chevrolet "
                "while his granddaughter stands beside him holding an airline ticket and a packed suitcase."
            ),
            vietnamese_text=(
                "Vào lúc bình minh ở Havana, một người thợ máy lớn tuổi người Cuba đang sửa chiếc "
                "Chevrolet đời 1955 đã phai màu, trong khi cháu gái của ông đứng bên cạnh, cầm vé máy bay "
                "và một chiếc va li đã được đóng sẵn."
            ),
            status="selected",
            context=SceneContext(
                subject=("elderly Cuban mechanic", "granddaughter"),
                action=("repairing classic car", "holding airline ticket"),
                location=("Havana", "Cuba", "street"),
                objects=("1955 Chevrolet", "suitcase", "airline ticket", "tools"),
                mood=("documentary", "family separation", "real life"),
                avoid=("modern garage", "modern car", "non-Cuban city"),
                keywords=("Havana mechanic", "classic Chevrolet", "Cuba street life"),
                suggested_sources=("YouTube", "Storyblocks", "News"),
            ),
        ),
        SceneRecord(
            scene_id="scene_002",
            order=2,
            english_text="His granddaughter stands beside him holding a ticket and a packed suitcase.",
            vietnamese_text="Cháu gái của ông đứng bên cạnh, cầm vé máy bay và một chiếc va li đã đóng sẵn.",
            status="selected",
            context=SceneContext(
                subject=("young Cuban woman", "granddaughter"),
                action=("standing with luggage",),
                location=("Havana",),
                objects=("suitcase", "ticket"),
                keywords=("Cuba family luggage", "Havana young woman suitcase"),
            ),
        ),
        SceneRecord(
            scene_id="scene_003",
            order=3,
            english_text="Cuban families are saying goodbye at the airport before another departure.",
            vietnamese_text="Các gia đình Cuba nói lời tạm biệt tại sân bay trước một chuyến đi khác.",
        ),
        SceneRecord(
            scene_id="scene_004",
            order=4,
            english_text="In Shanghai, office workers rush into the subway before another long day.",
            vietnamese_text="Tại Thượng Hải, nhân viên văn phòng vội vã vào tàu điện ngầm trước một ngày làm việc dài.",
        ),
        SceneRecord(
            scene_id="scene_005",
            order=5,
            english_text="Despite the difficulties, Cuban people continue with ordinary daily life.",
            vietnamese_text="Bất chấp những khó khăn, người dân Cuba vẫn tiếp tục cuộc sống thường ngày.",
        ),
    ]


def demo_candidates(scene_id: str) -> list[CandidateRecord]:
    """Return deterministic scene-specific candidates for the F001 GUI prototype.

    F001 still uses local demo data, but each scene must visibly produce different
    search results so selecting a scene in panel 4 exercises the same UX contract
    that real providers will use in F002.
    """
    rows_by_scene = {
        "scene_001": [
            ("youtube", "yt_havana_001", "Walking Through Havana – Classic Cars and Daily Life in Cuba 2025", 1938, .92, "creative_commons", "4K"),
            ("storyblocks", "sb_001", "Classic Car Repair in Havana – Stock Footage", 312, .88, "commercial", "4K"),
            ("pexels", "px_001", "Old Car on Havana Street", 756, .85, "stock", "HD"),
            ("news", "news_001", "Havana Residents Keep Classic Cars Alive", 564, .82, "editorial", "HD"),
            ("pixabay", "pb_001", "Cuban Street Life", 18, .78, "stock", "HD"),
            ("youtube", "yt_havana_002", "Cuban Mechanics Keep These Classic Cars Alive | Havana Streets", 1125, .76, "creative_commons", "1080p"),
        ],
        "scene_002": [
            ("pexels", "px_luggage_001", "Young Woman Waiting With Suitcase in Havana", 46, .91, "stock", "4K"),
            ("youtube", "yt_family_002", "Cuban Family Prepares for a Departure", 824, .87, "creative_commons", "1080p"),
            ("storyblocks", "sb_ticket_002", "Woman Holding Airline Ticket and Luggage", 34, .84, "commercial", "4K"),
            ("pixabay", "pb_suitcase_002", "Traveler With Packed Suitcase", 22, .80, "stock", "HD"),
            ("news", "news_family_002", "Young Cubans Prepare to Leave the Island", 402, .77, "editorial", "HD"),
            ("youtube", "yt_havana_woman_002", "Daily Life in Havana – Families and Travel", 960, .74, "creative_commons", "1080p"),
        ],
        "scene_003": [
            ("youtube", "yt_airport_003", "Emotional Goodbyes at Havana Airport", 688, .94, "creative_commons", "1080p"),
            ("news", "news_airport_003", "Cuban Families Say Goodbye Before Departure", 318, .91, "editorial", "HD"),
            ("storyblocks", "sb_airport_003", "Family Farewell at Airport Terminal", 42, .86, "commercial", "4K"),
            ("pexels", "px_airport_003", "Family Hugging Near Airport Check-in", 31, .82, "stock", "4K"),
            ("pixabay", "pb_airport_003", "Travelers With Luggage at Airport", 26, .79, "stock", "HD"),
            ("youtube", "yt_departure_003", "Havana Airport Departures and Family Farewells", 1040, .76, "creative_commons", "1080p"),
        ],
        "scene_004": [
            ("youtube", "yt_shanghai_004", "Shanghai Morning Rush Hour – Metro Commute", 1332, .93, "creative_commons", "4K"),
            ("storyblocks", "sb_subway_004", "Office Workers Enter Shanghai Subway", 38, .89, "commercial", "4K"),
            ("pexels", "px_metro_004", "Crowded Metro Commute in Modern Asian City", 28, .84, "stock", "4K"),
            ("news", "news_work_004", "China Office Workers Face Long Commutes", 446, .81, "editorial", "HD"),
            ("pixabay", "pb_station_004", "Business Commuters at Metro Station", 19, .77, "stock", "HD"),
            ("youtube", "yt_lujiazui_004", "Shanghai Workers Rush to the Subway", 901, .75, "creative_commons", "1080p"),
        ],
        "scene_005": [
            ("youtube", "yt_daily_005", "Everyday Life in Havana Neighborhoods", 1210, .90, "creative_commons", "4K"),
            ("news", "news_daily_005", "Ordinary Cubans Continue Daily Life Amid Hardship", 512, .88, "editorial", "HD"),
            ("storyblocks", "sb_street_005", "Cuban Street Market and Daily Routine", 36, .84, "commercial", "4K"),
            ("pexels", "px_people_005", "People Walking Through Havana Streets", 29, .81, "stock", "4K"),
            ("pixabay", "pb_market_005", "Caribbean Neighborhood Daily Life", 24, .77, "stock", "HD"),
            ("youtube", "yt_cuba_daily_005", "A Normal Day in Cuba – Streets, Shops and Families", 1088, .74, "creative_commons", "1080p"),
        ],
    }
    rows = rows_by_scene.get(scene_id, rows_by_scene["scene_001"])
    return [
        CandidateRecord(
            candidate_id=f"{scene_id}_cand_{index:03d}",
            scene_id=scene_id,
            provider=provider,
            source_id=source_id,
            title=title,
            duration=duration,
            score=score,
            rights_status=rights,
            resolution=resolution,
            proposed_start=436.0 + index * 12,
            proposed_end=441.0 + index * 12,
        )
        for index, (provider, source_id, title, duration, score, rights, resolution) in enumerate(rows, start=1)
    ]
