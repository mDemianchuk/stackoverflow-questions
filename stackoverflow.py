import time
import math
import logging
import asyncio
from pprint import pprint
from datetime import datetime, timedelta

import aiohttp
from aiohttp import ClientSession

logging.basicConfig(level=logging.INFO)


def get_week_ago_in_seconds() -> int:
    today = datetime.now()
    week_ago = today - timedelta(days=7)
    return math.floor(week_ago.timestamp())


class StackExchangeClient:
    def __init__(self, site: str, api_name: str):
        self.__site = site
        self.__base_url = f"https://api.stackexchange.com/2.3/{api_name}"
        # This filter was created at https://api.stackexchange.com/docs/create-filter
        # To only include relevant fields in the response body:
        # answer_count, link, view_count, creation_date, question_id
        self.__question_filter = "!m9aF_UAbWOtMBiDgLzfN4Q"

    async def fetch_top_n_unanswered_questions_async(
        self,
        session: ClientSession,
        tag: str,
        in_title: str,
        from_date: int,
        page_number: int,
        n: int,
        page_size: int = 100,
    ):
        query_params = {
            "tagged": tag,
            "intitle": in_title,
            "fromdate": from_date,
            "page": page_number,
            "pagesize": page_size,
            "sort": "creation",
            "site": self.__site,
            "filter": self.__question_filter,
        }
        logging.debug(f"Fetching page {page_number}")
        response = await session.get(self.__base_url, params=query_params)
        response_body = await response.json()

        if not response.ok:
            error_message = response_body.get("error_message", "Something went wrong.")
            error_code = response_body.get("error_id", 500)
            raise Exception(
                f"Unable to fetch page #{page_number}: {error_message} | Error code: {error_code}"
            )

        # Filter out and sort questions
        questions = response_body.get("items", [])
        unanswered_questions = self.remove_answered_questions(questions)
        top_n_questions = self.get_top_n_questions_by_view_count(
            unanswered_questions, n
        )

        # Calculate remaining page count
        total_question_count = response_body.get("total", 0)
        total_page_count = math.ceil(total_question_count / page_size)
        remaining_page_count = total_page_count - page_number
        return top_n_questions, remaining_page_count

    @staticmethod
    def is_answered(question: dict) -> bool:
        # Also removes field 'answer_count' to match the expected output
        return question.pop("answer_count", 0) > 0

    @classmethod
    def remove_answered_questions(cls, questions: list) -> list:
        return list(filter(lambda q: not cls.is_answered(q), questions))

    @staticmethod
    def get_top_n_questions_by_view_count(questions: list, n: int) -> list:
        sorted_questions = list(
            sorted(questions, key=lambda q: q["view_count"], reverse=True)
        )
        return sorted_questions[:n]


class StackOverflowController:
    def __init__(self):
        self.client = StackExchangeClient("stackoverflow", "search")

    async def get_top_n_unanswered_questions_async(
        self,
        tag: str,
        in_title: str = "",
        from_date: int = get_week_ago_in_seconds(),
        batch_size: int = 10,
        n: int = 5,
    ) -> list:
        async with ClientSession() as session:
            page_number = 1
            (
                top_n_questions,
                remaining_page_count,
            ) = await self.client.fetch_top_n_unanswered_questions_async(
                session, tag, in_title, from_date, page_number, n
            )
            while remaining_page_count > 0:
                current_page_count = remaining_page_count % batch_size or batch_size
                remaining_page_count -= current_page_count
                coroutines = []
                for i in range(current_page_count):
                    page_number += 1
                    coroutine = self.client.fetch_top_n_unanswered_questions_async(
                        session, tag, in_title, from_date, page_number, n
                    )
                    coroutines.append(coroutine)
                coroutine_result = await asyncio.gather(*coroutines)
                for top_n, _ in coroutine_result:
                    top_n_questions += top_n
                    top_n_questions = self.client.get_top_n_questions_by_view_count(
                        top_n_questions, n
                    )
            return top_n_questions


if __name__ == "__main__":
    controller = StackOverflowController()
    try:
        start_time = time.perf_counter()
        result = asyncio.run(controller.get_top_n_unanswered_questions_async("python"))
        pprint(result)
        logging.info(f"Batch processing time: {time.perf_counter() - start_time}")
    except aiohttp.ClientError as e:
        error_message = getattr(e, "message", "Something went wrong")
        logging.error(f"aiohttp error: {error_message}")
    except Exception as e:
        logging.error(f"non-aiohttp error: {e}")
