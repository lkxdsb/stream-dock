import unittest

import httpx

from app import app


class HomePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_page_renders_fetch_form(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            response = await client.get('/')

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn('<form', text)
        self.assertIn('name="link"', text)
        self.assertIn('name="outputPath"', text)
        self.assertIn('name="outputType"', text)
        self.assertIn('开始解析', text)


if __name__ == '__main__':
    unittest.main()
